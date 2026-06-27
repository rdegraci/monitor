"""Per-turn reasoning-effort auto-bump heuristic.

The harness inspects each user message before sending it to the LLM. If
the message looks like it'd benefit from deeper thinking — based on a
small list of keyword and length signals — the harness sets a per-turn
override that promotes reasoning_effort to "medium" for the duration of
that user turn. The override is ephemeral: it's set in prepare_query_context
and cleared the next time prepare_query_context runs (or when set_model /
:reset_history fires).

The heuristic is intentionally one-way: it only bumps UP (toward more
thinking), never down. A surprise downgrade on a hard task is riskier
than a surprise upgrade on a trivial one — so the worst case here is
slightly over-spending on a misclassified easy turn, never under-spending
on a misclassified hard one.

The heuristic also defers to the user's configured default: if
config.REASONING_EFFORT is already "medium" or above, the heuristic is a no-op
(can't go higher than what this heuristic suggests). Explicit inline turn
flags are handled by the conversation layer before this heuristic runs.
"""

import re

from monitor.lib.llm_model_utils import higher_reasoning_effort

# High-confidence reasoning-intent phrases grouped by theme.
# Root-cause / failure analysis phrases are the strongest indicators that the
# user wants careful diagnosis rather than a routine edit.
ROOT_CAUSE_AND_FAILURE_SIGNALS = (
    "root cause",
    "what caused this",
    "why is this happening",
    "why did this break",
    "what is going wrong",
    "why is it failing",
    "where is this coming from",
    "how does this fail",
    "failure mode",
)

# Verification / correctness phrases indicate the user wants the result
# checked, validated, or compared for safety before accepting it.
VERIFICATION_AND_CORRECTNESS_SIGNALS = (
    "verify the fix",
    "check for regressions",
    "confirm the behavior",
    "validate the change",
    "make sure this is safe",
    "assess the risk",
    "ensure compatibility",
    "prove that",
    "is this correct",
)

# Investigation / tracing phrases suggest the user wants the flow followed or
# the source of a problem located across code paths.
INVESTIGATION_AND_TRACING_SIGNALS = (
    "trace through",
    "trace the flow",
    "follow the path",
    "investigate the issue",
    "inspect the call chain",
    "track down",
    "locate the source",
    "find the bug",
    "identify the regression",
    "pinpoint the problem",
)

# Architecture / design phrases are useful when the user is asking for a
# broader system-level judgment or tradeoff analysis.
ARCHITECTURE_AND_DESIGN_SIGNALS = (
    "cross-file analysis",
    "system-wide impact",
    "architecture review",
    "design review",
    "tradeoff analysis",
)

# Review / audit style phrases point to explicit scrutiny of implementation
# quality, behavior, or edge cases.
REVIEW_AND_AUDIT_SIGNALS = (
    "audit the change",
    "review for regressions",
    "examine the behavior",
    "look for edge cases",
    "check the assumptions",
    "evaluate correctness",
)

# Broader but still useful phrasing for system scope or unexpected behavior.
BROAD_SCOPE_AND_BEHAVIOR_SIGNALS = (
    "across the codebase",
    "interactions between",
    "behavioral change",
    "unexpected behavior",
)

# Expensive high-effort routing signals are intentionally checked last so the
# more specific multi-word phrase groups above get first consideration.
HIGH_EFFORT_WORD_SIGNALS = (
    "debug",
    "trace",
    "investigate",
    "follow",
    "identify"
)

KEYWORD_SIGNALS = (
    *ROOT_CAUSE_AND_FAILURE_SIGNALS,
    *VERIFICATION_AND_CORRECTNESS_SIGNALS,
    *INVESTIGATION_AND_TRACING_SIGNALS,
    *ARCHITECTURE_AND_DESIGN_SIGNALS,
    *REVIEW_AND_AUDIT_SIGNALS,
    *BROAD_SCOPE_AND_BEHAVIOR_SIGNALS,
    *HIGH_EFFORT_WORD_SIGNALS,
)

# Messages above this character length suggest the user is providing
# substantial context (a paste, a multi-part description) that warrants
# more thinking. Tuned to avoid firing on routine one-liners like
# "fix the typo on line 42 in foo.py".
LENGTH_THRESHOLD = 500

# Messages with more than this many newline-separated lines also trigger.
# Multi-line input usually means a multi-part request or a structured ask.
LINE_COUNT_THRESHOLD = 3

# Reasoning levels accepted by the providers, ranked from low to high. Used to
# decide whether to bump — a bump fires only when the current effort is below
# the EFFECTIVE target (the default below, raised by REASONING_BUMP_EFFORT).
_EFFORT_RANK = {"minimal": 0, "low": 1, "medium": 2, "high": 3, "xhigh": 4}

# The effort an auto-bump promotes to by default. REASONING_BUMP_EFFORT can
# raise this (via _effective_bump_target) but never lower it below medium, so
# the bump is always at least a "think harder" nudge.
_BUMP_TARGET = "medium"


def _effective_bump_target(bump_floor):
    """The effort an auto-bump promotes to: ``_BUMP_TARGET`` raised by the
    configured floor (``REASONING_BUMP_EFFORT``).

    The floor can only raise the target — a floor at or below medium leaves it
    at medium. This is what lets a steady ``medium`` config still bump (e.g. to
    ``high``) while a steady ``medium`` with no floor stays a no-op.

    Args:
        bump_floor: The configured minimum bump effort, or None/invalid.

    Returns:
        The effective target effort label.
    """
    return higher_reasoning_effort(_BUMP_TARGET, bump_floor)


def detect_reasoning_bump(user_text, current_effort, bump_floor=None):
    """Decide whether the current user message warrants bumping reasoning
    effort for this turn.

    Args:
        user_text: The user's message text (post-macro-expansion, as it
            will go to the LLM). None or empty returns None.
        current_effort: The currently configured reasoning effort
            (config.REASONING_EFFORT). When already at or above the effective
            target, this returns None — never downgrades, never fires a no-op.
        bump_floor: Optional configured floor (config.REASONING_BUMP_EFFORT)
            that raises the bump target above the default medium.

    Returns:
        The effective bump target (medium, raised by ``bump_floor``) if the
        heuristic recommends bumping; None otherwise.
    """
    if not user_text or not isinstance(user_text, str):
        return None

    # Fire only when the bump would actually RAISE effort above the current
    # steady level. Comparing against the floored target (not a hardcoded
    # medium) is what lets a steady "medium" config bump to "high" when a floor
    # is set, while keeping a floor-less medium config a no-op.
    target = _effective_bump_target(bump_floor)
    current_rank = _EFFORT_RANK.get(
        (current_effort or "").lower(), _EFFORT_RANK["low"]
    )
    if current_rank >= _EFFORT_RANK.get(target, _EFFORT_RANK[_BUMP_TARGET]):
        return None

    # Keyword detection. Lower-case the whole message for case-insensitive
    # matching. Multi-word phrases ("review for") are matched as substring;
    # single words use word boundaries so we don't fire on "alignment" when
    # the signal is "align" — that level of false-positive matters here
    # since "align" is broad enough already.
    text_lower = user_text.lower()
    for signal in KEYWORD_SIGNALS:
        if " " in signal:
            if signal in text_lower:
                return target
        else:
            # Match against the original user text instead of a lower-cased copy.
            # Macros may expand to uppercase tokens like DEBUG, and those should
            # not accidentally trigger these single-word reasoning signals.
            if re.search(rf"\b{re.escape(signal)}\b", user_text):
                return target
            if re.search(rf"\b{re.escape(signal.title())}\b", user_text):
                return target

    # Length-based fallback.
    if len(user_text) > LENGTH_THRESHOLD:
        return target

    if user_text.count("\n") + 1 > LINE_COUNT_THRESHOLD:
        return target

    return None


