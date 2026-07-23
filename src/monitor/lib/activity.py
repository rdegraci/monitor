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

While waiting on the model, the spinner label is ``pre-processing`` before any
tool (``[RT 1 · pre-processing ⠋ 2s]``), or the last tool plus
``processing results`` afterward
(``[RT 3 · ripgrep_search_tool · processing results ⠋ 5s]``). Token and cost
figures stay in spend logs / the status line — not on this spinner.
Tool-running updates are tracked for the TUI but not painted to stderr; they
were cleared immediately for tool stdout and only flashed briefly.
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
# rely on them. STATE_WAITING is a sentinel; display text is resolved in
# format_activity (pre-processing vs processing results).
STATE_WAITING = "waiting"
STATE_RUNNING = "running"
STATE_COMPACTING = "compacting"
STATE_RETRYING = "retrying"
STATE_FAILED = "failed"

WAITING_PRE = "pre-processing"
WAITING_RESULTS = "processing results"

# Tracks whether we've painted anything this turn so ``clear`` only emits the
# erase sequence when there is something to erase.
_painted = {"value": False}

# Latest activity text for surfaces that don't read stderr (notably the TUI
# info bar). Updated whenever feedback is enabled, independent of whether the
# stderr line was painted. ``None`` means "no active status".
_last_text = {"value": None}

# Most recently named tool this turn. Used so the model-wait spinner can show
# context (last tool) instead of a generic wait label. Cleared by ``clear()``.
_last_tool = {"value": None}


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


def format_activity(
    state: str,
    *,
    rt_count=None,
    tool=None,
) -> str:
    """Build a compact, payload-free activity string.

    Examples:
        ``RT 1 · pre-processing`` (waiting, no tool yet)
        ``RT 3 · run_python_tests · processing results`` (waiting after a tool)
        ``RT 3 · run_python_tests`` (tool running; TUI only)
        ``RT 2 · modify_source_code · retrying``

    Args:
        state: One of the ``STATE_*`` constants.
        rt_count: Round-trip index for the turn (optional).
        tool: Tool name only — never arguments (optional).
    """
    parts: list[str] = []
    if rt_count is not None:
        parts.append(f"RT {rt_count}")
    if tool:
        parts.append(str(tool))
    # RUNNING never labels itself. WAITING resolves to a phase-specific phrase.
    if state == STATE_WAITING:
        parts.append(WAITING_RESULTS if tool else WAITING_PRE)
    elif state and state != STATE_RUNNING:
        parts.append(state)
    return " · ".join(parts) if parts else (state or "")


def show(
    state: str,
    *,
    rt_count=None,
    tool=None,
) -> None:
    """Record (and often paint) one activity line for the current turn.

    No-op when feedback is disabled. Records the text for non-stderr surfaces
    (TUI). ``STATE_RUNNING`` updates tracked text / last-tool but does not
    paint to stderr — tool stdout would immediately overwrite it. Other states
    paint an in-place line when stderr is a TTY.
    """
    if not feedback_enabled():
        return
    try:
        if tool:
            _last_tool["value"] = str(tool)
        effective_tool = tool
        if state == STATE_WAITING and not effective_tool:
            effective_tool = _last_tool["value"]
        text = format_activity(
            state,
            rt_count=rt_count,
            tool=effective_tool,
        )
        _last_text["value"] = text
        if not activity_enabled():
            return
        # Tool-running updates are for the TUI / next wait label only.
        if state == STATE_RUNNING:
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
    _last_tool["value"] = None
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
