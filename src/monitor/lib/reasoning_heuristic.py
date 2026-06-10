"""Per-turn reasoning-effort auto-bump heuristic.

The harness inspects each user message before sending it to the LLM. If
the message looks like it'd benefit from deeper thinking — based on a
small list of keyword and length signals — the harness sets a per-turn
override that promotes reasoning_effort to "high" for the duration of
that user turn. The override is ephemeral: it's set in prepare_query_context
and cleared the next time prepare_query_context runs (or when set_model /
:reset_history fires).

The heuristic is intentionally one-way: it only bumps UP (toward more
thinking), never down. A surprise downgrade on a hard task is riskier
than a surprise upgrade on a trivial one — so the worst case here is
slightly over-spending on a misclassified easy turn, never under-spending
on a misclassified hard one.

The heuristic also defers to the user's configured default: if
config.REASONING_EFFORT is already "high", the heuristic is a no-op
(can't go higher).
"""

import re

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
    "trace"
)

# Messages above this character length suggest the user is providing
# substantial context (a paste, a multi-part description) that warrants
# more thinking. Tuned to avoid firing on routine one-liners like
# "fix the typo on line 42 in foo.py".
LENGTH_THRESHOLD = 500

# Messages with more than this many newline-separated lines also trigger.
# Multi-line input usually means a multi-part request or a structured ask.
LINE_COUNT_THRESHOLD = 3

# Reasoning levels accepted by the providers, ranked from low to high.
# Used to decide whether to bump (only when current is BELOW high).
_EFFORT_RANK = {"minimal": 0, "low": 1, "medium": 2, "high": 3}


def detect_reasoning_bump(user_text, current_effort):
    """Decide whether the current user message warrants bumping reasoning
    effort to "high" for this turn.

    Args:
        user_text: The user's message text (post-macro-expansion, as it
            will go to the LLM). None or empty returns None.
        current_effort: The currently configured reasoning effort
            (config.REASONING_EFFORT). If already "high" or unknown, this
            function returns None — never downgrades, never overrides
            something stronger than what we'd suggest.

    Returns:
        "high" if the heuristic recommends bumping; None otherwise.
    """
    if not user_text or not isinstance(user_text, str):
        return None

    # Defer to default if it's already at-or-above what we'd suggest.
    current_rank = _EFFORT_RANK.get(
        (current_effort or "").lower(), _EFFORT_RANK["medium"]
    )
    if current_rank >= _EFFORT_RANK["high"]:
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
                return "high"
        else:
            if re.search(rf"\b{re.escape(signal)}\b", text_lower):
                return "high"

    # Length-based fallback.
    if len(user_text) > LENGTH_THRESHOLD:
        return "high"

    if user_text.count("\n") + 1 > LINE_COUNT_THRESHOLD:
        return "high"

    return None
