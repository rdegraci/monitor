"""Progress indicator for long-running blocking calls (mainly LLM completions).

Renders an animated single-line spinner with an elapsed-seconds counter:

    [Processing ⠋ 12s]

The line is repainted in place via ``\\r``, so it occupies one terminal line
regardless of how long the operation runs (compare to the previous
dot-accumulator, which grew unbounded). In non-TTY contexts (--script mode,
piped stderr, CI logs) the indicator is a silent no-op — see the rationale
in the function docstring.

The function name ``progress_dots`` is preserved across the dots→spinner
rewrite so the existing call sites in monitor.core.llm,
monitor.core.llm_responses_adapter, and monitor.lib.protocol_engine don't
need to change. Same applies to the existing test patches that mock
``progress_dots`` by name.
"""

from contextlib import contextmanager
import os
import sys
import threading
import time
from typing import Iterator, Optional


# Braille-dot spinner. Ten frames, each one byte of visual rotation —
# wider terminal support than full-block spinners and reads as smooth
# animation at 100ms/frame. Used by every modern CLI tool (yaspin, halo,
# ora, etc.) because the glyphs are unambiguous and consistent across
# common monospace fonts. ASCII fallback isn't included here: TTY mode
# in 2026 can safely assume unicode terminal output.
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Initial delay before the spinner becomes visible. Operations that
# complete in under this window never paint anything — keeps fast
# turns flicker-free instead of "spinner appears then immediately
# vanishes."
_INITIAL_DELAY_SECONDS = 0.3

# ANSI escape: \r returns cursor to column 0, \033[2K erases the entire
# line. Together they wipe the repainted indicator cleanly so the next
# output starts on a fresh line. \r alone would leave the rendered
# indicator visible (next text overwrites only its prefix).
_ERASE_LINE = "\r\033[2K"


@contextmanager
def progress_dots(message: Optional[str] = None, interval: float = 0.1) -> Iterator[None]:
    """Animated spinner + elapsed-seconds indicator while a blocking
    operation runs. Single-line, in-place repaint, stderr only.

    Output shape::

        [Processing ⠋ 12s]

    When ``message`` is omitted and live turn feedback has an active activity
    string (PLAN Phase 3), that string is used as the spinner label instead —
    e.g. ``[RT 3 · request sent - processing ⠋ 12s]`` — so the familiar spinner and the RT/tool
    context share one line instead of overwriting each other.

    The spinner cycles at ``interval`` seconds per frame (default 0.1s =
    10fps, conventional for spinner libraries) and the elapsed counter
    ticks every second. After a brief startup grace window
    (_INITIAL_DELAY_SECONDS) the indicator appears; on context exit it's
    erased so subsequent output is unaffected.

    TTY gate
    --------
    The indicator is suppressed in non-TTY contexts: ``--script`` mode,
    piped stderr, CI logs, the bench runner. Reason: repainted ANSI
    output (`\\r` + erase-line) renders as ugly noise in captured logs
    and breaks the bench's stderr-tail parsing. Set
    ``MONITOR_FORCE_PROGRESS=1`` to override the gate (useful for
    debugging the indicator in non-TTY tests).

    This is a deliberate behavior change from the prior dot-accumulator
    implementation, which printed the message + newline once even on
    non-TTY. Callers that relied on the non-TTY message echo should
    use ``logging.info(message)`` directly.

    Args:
        message: Label shown in the indicator, defaults to the current
                 live-activity string when available, otherwise
                 "Processing". Whitespace is trimmed; embedded ``]``
                 chars are kept (the indicator's closing bracket is
                 appended literally).
        interval: Spinner frame interval in seconds (default 0.1).

    Yields:
        None. Use in a with-statement to bound the indicator's lifetime.

    Example::

        with progress_dots("Sending request"):
            blocking_llm_call()
    """
    force = bool(os.getenv("MONITOR_FORCE_PROGRESS"))
    is_terminal = sys.stderr.isatty()

    # Non-TTY fallback: truly silent. The wrapped operation still runs;
    # we just don't paint anything.
    if not is_terminal and not force:
        yield
        return

    fixed_label = None
    if message is not None:
        fixed_label = (message or "Processing").strip() or "Processing"

    def _resolve_label() -> str:
        if fixed_label is not None:
            return fixed_label
        try:
            from monitor.lib import activity

            current = activity.current_activity()
            if isinstance(current, str) and current.strip():
                return current.strip()
        except Exception:
            pass
        return "Processing"

    stop_event = threading.Event()
    started = time.monotonic()

    # Tracks whether the spinner ever painted, so the erase-line on
    # exit is skipped for the "operation completed before the initial
    # delay elapsed" case. Without this guard, a sub-300ms operation
    # would emit an erase-line escape into terminals that never saw
    # any spinner — harmless on most terminals, ugly on some.
    painted = {"value": False}

    def _animate() -> None:
        # stop_event.wait returns True if signaled, False on timeout.
        # If the context exits during the initial delay, bail out
        # without painting anything.
        if stop_event.wait(_INITIAL_DELAY_SECONDS):
            return
        frame_idx = 0
        while not stop_event.is_set():
            elapsed_s = int(time.monotonic() - started)
            ch = _SPINNER_FRAMES[frame_idx % len(_SPINNER_FRAMES)]
            label = _resolve_label()
            try:
                sys.stderr.write(f"\r[{label} {ch} {elapsed_s}s]")
                sys.stderr.flush()
            except (BrokenPipeError, OSError):
                # stderr closed (parent process died, redirect broke).
                # Exit the loop rather than spin forever throwing.
                return
            painted["value"] = True
            frame_idx += 1
            if stop_event.wait(interval):
                break

    thread = threading.Thread(target=_animate, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        # 2.0s join cap matches the prior implementation — generous
        # enough that a stuck animate thread (shouldn't happen, but
        # defensive) doesn't hang the REPL on every exit.
        thread.join(timeout=2.0)
        if painted["value"]:
            try:
                sys.stderr.write(_ERASE_LINE)
                sys.stderr.flush()
            except (BrokenPipeError, OSError):
                pass
            # The spinner owned the line; activity's paint flag is stale.
            try:
                from monitor.lib import activity

                activity.mark_line_cleared()
            except Exception:
                pass
