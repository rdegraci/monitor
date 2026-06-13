"""Error-driven reasoning escalation (the "reactive fallback" pattern).

Companion to ``reasoning_heuristic.py``. Where that module inspects the USER's
message up front to decide reasoning effort, this one reacts to TOOL RESULTS
mid-turn: when a tool's output looks like a failure (a test/build/lint error,
a Python traceback, a non-zero exit), the harness escalates ``reasoning_effort``
to "high" for the remaining LLM calls in the CURRENT turn, so the model reasons
harder about the fix instead of flailing at the default tier.

Same disciplines as the up-front heuristic:
- One-way: only escalates UP, never down.
- Pay-for-what-you-use: fires only when a failure is actually observed, so the
  expensive tier is reserved for turns with proven trouble. A missed escalation
  just keeps the default tier (no worse than today); a false escalation spends
  high-reasoning tokens for nothing — so the patterns favor PRECISION over
  recall and target unambiguous failure shapes, not routine prose containing
  the word "error".
- Sticky within the turn: once escalated, it stays high until the turn ends
  (CURRENT_TURN_REASONING_OVERRIDE is reset per user turn in
  prepare_query_context). A turn that already failed once is treated as hard for
  its remainder rather than flip-flopping tiers on every tool round.
"""

import re

# Failure markers. Matched with re.MULTILINE so ``^``-anchored patterns catch
# line-leading tokens (pytest's "FAILED", Go's "panic:"). Kept deliberately
# specific: each entry is a shape that reliably means "something broke", not a
# word that merely co-occurs with trouble.
_FAILURE_PATTERNS = (
    r"Traceback \(most recent call last\)",   # Python traceback
    # CamelCase exception at the START of a line — how an uncaught/printed
    # exception renders ("ValueError: ..."). Anchored to ^ so it does NOT fire
    # on source the model merely READ or grepped, where the name is indented
    # ("    except ValueError:") or prefixed ("foo.py:42:  raise ValueError").
    # That distinction matters a lot in a coding harness, where reading code
    # containing exception names is constant and must not cost extra tokens.
    r"^[A-Z]\w*(?:Error|Exception)\b",
    r"\b\d+ failed\b",                         # pytest/jest summary: "3 failed"
    r"^FAILED\b",                              # pytest -q / jest line
    r"^FAIL\b",                                # go test / jest "FAIL"
    r"npm ERR!",
    r"\berror TS\d+\b",                        # TypeScript compiler
    r"error\[E\d+\]",                          # Rust compiler
    r"\bSegmentation fault\b",
    r"^panic:",                                # Go panic
    r"command not found",
    r"\bexit (?:code|status):? *[1-9]\d*\b",   # explicit non-zero exit
    r"\bnon-zero exit\b",
)

_COMPILED = [re.compile(p, re.MULTILINE) for p in _FAILURE_PATTERNS]

# Effort ranking (mirrors reasoning_heuristic._EFFORT_RANK). Escalation only
# does something when the current effort is BELOW high.
_EFFORT_RANK = {"minimal": 0, "low": 1, "medium": 2, "high": 3}


def looks_like_failure(text):
    """True if ``text`` (a tool result or error string) contains a recognizable
    failure signal. None / empty / non-str returns False.
    """
    if not text or not isinstance(text, str):
        return False
    for pat in _COMPILED:
        if pat.search(text):
            return True
    return False


def should_escalate(current_effort):
    """Whether escalating to "high" would change anything given the current
    effort. False when already at or above high (escalation would be a no-op),
    so callers can skip the override and the log line.
    """
    rank = _EFFORT_RANK.get((current_effort or "").lower(), _EFFORT_RANK["medium"])
    return rank < _EFFORT_RANK["high"]
