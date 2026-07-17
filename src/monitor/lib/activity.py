"""Live turn/tool activity feedback (PLAN Phase 3).

A healthy multi-round-trip turn can take many seconds while the model reasons
and tools run. Without any signal the REPL looks stalled. This module renders a
single, in-place, payload-free activity line to stderr at meaningful turn
boundaries (request start, tool start, tool completion, compaction, retry).

Design constraints:

- Reuse the existing token/cost ledgers on :mod:`monitor.config`; never start a
  second accounting system and never issue a model call.
- Never print tool arguments, tool output, prompts, or credentials — tool names
  and aggregate counters only.
- Single rewriting line via ``\\r`` + erase, mirroring
  :func:`monitor.lib.progress.progress_dots`, so the REPL prompt is not
  corrupted.
- Silent in non-TTY (``--script``, pipes, CI) and server/subagent contexts,
  overridable with ``MONITOR_FORCE_PROGRESS=1`` for tests/debugging.
"""

from __future__ import annotations

import logging
import os
import sys

from monitor import config

logger = logging.getLogger(__name__)

# ANSI: return to column 0 and erase the whole line before repainting.
_ERASE_LINE = "\r\033[2K"

# Recognized activity states. Kept small and stable so tests and the TUI can
# rely on them.
STATE_WAITING = "request sent - processing"
STATE_RUNNING = "running"
STATE_COMPACTING = "compacting"
STATE_RETRYING = "retrying"
STATE_FAILED = "failed"

# Tracks whether we've painted anything this turn so ``clear`` only emits the
# erase sequence when there is something to erase.
_painted = {"value": False}

# Latest activity text for surfaces that don't read stderr (notably the TUI
# info bar). Updated whenever feedback is enabled, independent of whether the
# stderr line was painted. ``None`` means "no active status".
_last_text = {"value": None}


def feedback_enabled() -> bool:
    """Return True when live activity feedback is turned on (config-level)."""
    if not bool(getattr(config, "LIVE_TURN_FEEDBACK", True)):
        return False
    if getattr(config, "SERVER_MODE", False):
        return False
    if getattr(config, "AGENT", False):
        return False
    return True


def activity_enabled() -> bool:
    """Return True when live activity feedback should paint to stderr.

    On by default for interactive TTY REPL use; suppressed for non-TTY
    (``--script`` / piped / CI), server mode, and spawned sub-agents. The
    ``MONITOR_FORCE_PROGRESS`` env var forces rendering for tests/debugging.
    """
    if not feedback_enabled():
        return False
    if os.getenv("MONITOR_FORCE_PROGRESS"):
        return True
    try:
        return sys.stderr.isatty()
    except Exception:
        return False


def current_activity():
    """Return the latest activity text, or ``None`` if idle.

    Intended for non-stderr surfaces such as the TUI info bar.
    """
    return _last_text["value"]


def _current_turn_index() -> int:
    """Index of the in-flight turn within the per-turn ledgers."""
    costs = getattr(config, "TURN_COSTS_USD", None)
    if isinstance(costs, list) and costs:
        return len(costs) - 1
    return 0


def _ledger_value(name: str, default=0):
    """Read the current turn's value from a per-turn ledger list."""
    values = getattr(config, name, None)
    index = _current_turn_index()
    if isinstance(values, list) and 0 <= index < len(values):
        value = values[index]
        if isinstance(value, (int, float)):
            return value
    return default


def _format_tokens(count) -> str:
    """Render a token count compactly (e.g. 8200 -> '8.2k')."""
    try:
        count = int(count)
    except (TypeError, ValueError):
        return "0"
    if count < 1000:
        return str(count)
    return f"{count / 1000:.1f}k"


def format_activity(
    state: str,
    *,
    rt_count=None,
    tool=None,
    input_tokens=None,
    cost_usd=None,
) -> str:
    """Build a compact, payload-free activity string.

    Example: ``RT 3 · run_python_tests · 8.2k input · $0.14 turn``.

    Args:
        state: One of the ``STATE_*`` constants.
        rt_count: Round-trip index for the turn (optional).
        tool: Tool name only — never arguments (optional).
        input_tokens: Billed input tokens so far this turn (optional).
        cost_usd: Turn cost so far in USD (optional).
    """
    parts: list[str] = []
    if rt_count is not None:
        parts.append(f"RT {rt_count}")
    if tool:
        parts.append(str(tool))
    if state and state != STATE_RUNNING:
        parts.append(state)
    if input_tokens is not None:
        parts.append(f"{_format_tokens(input_tokens)} input")
    if cost_usd is not None:
        try:
            parts.append(f"${float(cost_usd):.2f} turn")
        except (TypeError, ValueError):
            pass
    return " · ".join(parts) if parts else (state or "")


def show(
    state: str,
    *,
    rt_count=None,
    tool=None,
) -> None:
    """Paint one in-place activity line for the current turn.

    No-op when feedback is disabled. Records the text for non-stderr surfaces
    (TUI) and, when stderr is a TTY, paints an in-place line. Pulls token/cost
    figures from the canonical per-turn ledgers; adds no model calls.
    """
    if not feedback_enabled():
        return
    try:
        text = format_activity(
            state,
            rt_count=rt_count,
            tool=tool,
            input_tokens=int(getattr(config, "LAST_BILLED_INPUT_TOKENS", 0) or 0) or None,
            cost_usd=_ledger_value("TURN_COSTS_USD", 0.0) or None,
        )
        _last_text["value"] = text
        if not activity_enabled():
            return
        sys.stderr.write(f"{_ERASE_LINE}[{text}]")
        sys.stderr.flush()
        _painted["value"] = True
    except (BrokenPipeError, OSError):
        pass
    except Exception:
        logger.debug("activity.show failed", exc_info=True)


def clear() -> None:
    """Erase the activity line and reset tracked state at turn end."""
    _last_text["value"] = None
    if not _painted["value"]:
        return
    try:
        sys.stderr.write(_ERASE_LINE)
        sys.stderr.flush()
    except (BrokenPipeError, OSError):
        pass
    finally:
        _painted["value"] = False


def mark_line_cleared() -> None:
    """Note that another renderer (e.g. ``progress_dots``) erased the line.

    Keeps the tracked activity text for the TUI / next spinner label, but
    clears the paint flag so ``clear()`` does not emit a redundant erase.
    """
    _painted["value"] = False


def suspend_paint() -> None:
    """Erase the painted status line without clearing tracked activity text.

    Used immediately before a tool runs so its stdout (diffs, ripgrep hits,
    etc.) is not corrupted by an in-place stderr rewrite. The TUI and the
    next ``progress_dots`` spinner still see :func:`current_activity`.
    """
    if not _painted["value"]:
        return
    try:
        sys.stderr.write(_ERASE_LINE)
        sys.stderr.flush()
    except (BrokenPipeError, OSError):
        pass
    finally:
        _painted["value"] = False
