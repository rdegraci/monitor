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
(can't go higher than what this heuristic suggests).
"""

import re

from monitor.lib.llm_model_utils import higher_reasoning_effort

# Keywords that signal the user is asking for work where deeper reasoning
# typically pays off. Whole-word matching so "refactor" matches but
# "refactoring" / "refactored" / "refactorize" don't accidentally fire
# substring rules elsewhere. Phrases like "review for" are matched as a
# multi-word substring (just lower-cased text search, not whole-word).
KEYWORD_SIGNALS = (
    "refactor",
    "audit",
    "design",
    "review for",
    "analyze",
    "debug",
    "architecture",
    "cross-file",
    "migrate",
    "align",
    "why",
    "examine",
    "trace",
    "verify",
    "fix"
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
            if re.search(rf"\b{re.escape(signal)}\b", text_lower):
                return target

    # Length-based fallback.
    if len(user_text) > LENGTH_THRESHOLD:
        return target

    if user_text.count("\n") + 1 > LINE_COUNT_THRESHOLD:
        return target

    return None


# --- Continuity bump (short confirmations after a substantive proposal) ---
#
# Short confirmations like "Sounds good. Proceed." carry no complexity keyword,
# so detect_reasoning_bump leaves them at the default tier — even though the
# turn they trigger is the EXECUTION of whatever was just proposed. This bump
# closes that gap: when the new message is a brief confirmation AND the previous
# assistant reply contained a concrete proposal (real code or a diff), reason at
# "medium" for the execution turn. Same one-way discipline as above.

# Anchored confirmation matcher (per the agreed r"^(proceed|...)" shape). "^"
# means leading filler defeats it, so "sounds good" / "looks good" are included
# explicitly to catch the natural "Sounds good. Proceed." phrasing.
_CONFIRMATION_RE = re.compile(
    r"^(proceed|go ahead|go for it|do it|do that|yes|yep|yeah|sure|ok|okay|"
    r"apply|make (?:those|the) changes|run it|sounds good|looks good|lgtm)\b",
    re.IGNORECASE,
)

# Only treat a message as a pure confirmation when it's brief — a longer message
# starting with "yes, but also refactor X" carries its own intent (and would hit
# the keyword heuristic anyway).
CONFIRMATION_MAX_WORDS = 8

# Concrete-proposal signals in the previous assistant reply. Unified-diff hunk
# headers / "diff --git" are unambiguous; the fenced-code path additionally
# requires a size floor so a trivial inline snippet doesn't qualify.
_DIFF_RE = re.compile(r"(?m)^(?:@@ -\d|diff --git )")
PLAN_MIN_CHARS = 200

# Prose-plan signal: an enumerated/bulleted list of steps ("1." / "2)" / "- ").
# A plan you'd reply "proceed" to is almost always STRUCTURED as steps, so we
# treat a multi-item list as a real proposal even with no code. Flowing prose
# WITHOUT a list is deliberately NOT a plan — that's the "ok thanks" after an
# ordinary explanation case, where there's nothing to execute and high effort
# would be wasted. Requiring >= 2 items keeps a stray single bullet from firing.
_PLAN_LIST_RE = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+\S")
PLAN_MIN_LIST_ITEMS = 2


def _last_assistant_text(conversation_history):
    """Return the content of the most recent assistant message that actually has
    text (skipping tool-call-only messages), or None.
    """
    if not isinstance(conversation_history, list):
        return None
    for msg in reversed(conversation_history):
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content
    return None


def _looks_substantive(assistant_text):
    """True if the assistant reply contains a concrete proposal worth executing
    at elevated effort:
      - a unified diff, or
      - a real fenced code block (size-gated against trivial snippets), or
      - a prose plan structured as an enumerated/bulleted list of >= 2 steps.
    Unstructured flowing prose does NOT qualify (nothing to execute).
    """
    if not assistant_text or not isinstance(assistant_text, str):
        return False
    if _DIFF_RE.search(assistant_text):
        return True
    if assistant_text.count("```") >= 2 and len(assistant_text) >= PLAN_MIN_CHARS:
        return True
    if len(_PLAN_LIST_RE.findall(assistant_text)) >= PLAN_MIN_LIST_ITEMS:
        return True
    return False


def detect_continuation_bump(user_text, conversation_history, current_effort, bump_floor=None):
    """Decide whether a short confirmation should inherit the bump target because
    the previous assistant turn proposed something concrete to execute.

    Returns the effective (floored) bump target when: current effort is below
    that target, the message is a brief confirmation (matches _CONFIRMATION_RE
    and <= CONFIRMATION_MAX_WORDS words), and the last assistant reply
    _looks_substantive. Otherwise None.

    Args:
        user_text: The user's message text. None or empty returns None.
        conversation_history: The conversation history list.
        current_effort: The currently configured reasoning effort.
        bump_floor: Optional configured floor (config.REASONING_BUMP_EFFORT)
            that raises the bump target above the default medium.
    """
    if not user_text or not isinstance(user_text, str):
        return None

    target = _effective_bump_target(bump_floor)
    current_rank = _EFFORT_RANK.get(
        (current_effort or "").lower(), _EFFORT_RANK["low"]
    )
    if current_rank >= _EFFORT_RANK.get(target, _EFFORT_RANK[_BUMP_TARGET]):
        return None

    stripped = user_text.strip()
    if len(stripped.split()) > CONFIRMATION_MAX_WORDS:
        return None
    if not _CONFIRMATION_RE.match(stripped):
        return None

    prev = _last_assistant_text(conversation_history)
    if _looks_substantive(prev):
        return target
    return None
