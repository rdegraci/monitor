"""Tests for the animated spinner progress indicator (monitor.lib.progress).

The function was rewritten from a dot-accumulator to a single-line
spinner-plus-elapsed indicator. Tests pin the new contract:

- Non-TTY mode → completely silent (no message echo, no spinner).
- TTY mode → paints ``[label spinner-glyph Ns]`` on stderr, repainted
  via ``\\r``, then erased on exit.
- ``MONITOR_FORCE_PROGRESS`` overrides the TTY gate.
- Sub-initial-delay operations paint nothing (no flicker).
- ``thread.join`` happens on context exit (no leaked background threads).
"""

import io
import re
import sys
import threading
import time

import pytest

from monitor.lib.progress import progress_dots, _SPINNER_FRAMES


class _FakeStderr(io.StringIO):
    """StringIO that lies about isatty so we can drive both code paths
    deterministically — the real stderr's TTY status depends on how the
    test runner is invoked."""

    def __init__(self, is_tty: bool):
        super().__init__()
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


# ---------------------------------------------------------------------------
# Non-TTY: silent no-op
# ---------------------------------------------------------------------------


def test_non_tty_writes_nothing(monkeypatch):
    """The deliberate behavior change from the prior implementation: in
    non-TTY mode we paint nothing at all. Even the message is not
    echoed — callers that wanted that should log explicitly."""
    fake = _FakeStderr(is_tty=False)
    monkeypatch.setattr(sys, "stderr", fake)
    monkeypatch.delenv("MONITOR_FORCE_PROGRESS", raising=False)

    with progress_dots("hello", interval=0.01):
        time.sleep(0.05)  # give a spinner ample chance to paint

    assert fake.getvalue() == ""


def test_non_tty_message_unused(monkeypatch):
    """Even with a long-running operation in non-TTY mode, no output
    leaks. The bench runner relies on this — repainted ANSI escapes in
    captured stderr would corrupt the bench's stderr_tail parser."""
    fake = _FakeStderr(is_tty=False)
    monkeypatch.setattr(sys, "stderr", fake)
    monkeypatch.delenv("MONITOR_FORCE_PROGRESS", raising=False)

    with progress_dots("longer", interval=0.01):
        time.sleep(0.5)  # well past initial delay; would paint on TTY

    assert fake.getvalue() == ""


# ---------------------------------------------------------------------------
# TTY: spinner + elapsed counter
# ---------------------------------------------------------------------------


def test_tty_paints_spinner_with_label_and_elapsed(monkeypatch):
    fake = _FakeStderr(is_tty=True)
    monkeypatch.setattr(sys, "stderr", fake)
    monkeypatch.delenv("MONITOR_FORCE_PROGRESS", raising=False)

    with progress_dots("Sending", interval=0.01):
        # Sleep well past the 0.3s initial delay so several frames paint.
        time.sleep(0.6)

    out = fake.getvalue()
    # Repainted: each frame is prefixed with \r.
    assert "\r" in out
    # Label appears.
    assert "Sending" in out
    # At least one spinner glyph appears.
    assert any(ch in out for ch in _SPINNER_FRAMES)
    # Elapsed-seconds counter format: "Ns" where N is an integer.
    # After ~0.6s of total wait (0.3s delay + ~0.3s painting), we should
    # see at least the "0s" frame.
    assert re.search(r"\b\d+s\b", out)


def test_tty_default_label_is_processing(monkeypatch):
    """Calling progress_dots() with no message must paint the default
    'Processing' label — the most common call site shape in monitor."""
    fake = _FakeStderr(is_tty=True)
    monkeypatch.setattr(sys, "stderr", fake)
    monkeypatch.delenv("MONITOR_FORCE_PROGRESS", raising=False)

    with progress_dots(interval=0.01):
        time.sleep(0.5)

    out = fake.getvalue()
    assert "Processing" in out


def test_tty_erases_line_on_exit(monkeypatch):
    """After the context exits, the indicator must be erased so the
    next stdout/stderr write starts on a clean line. \\033[2K is ANSI
    'erase entire line'."""
    fake = _FakeStderr(is_tty=True)
    monkeypatch.setattr(sys, "stderr", fake)
    monkeypatch.delenv("MONITOR_FORCE_PROGRESS", raising=False)

    with progress_dots("x", interval=0.01):
        time.sleep(0.5)

    out = fake.getvalue()
    # The erase sequence appears at the END of the output (after all the
    # repainted frames).
    assert out.endswith("\r\033[2K")


def test_tty_short_operation_paints_nothing(monkeypatch):
    """Operations that complete before the initial-delay window
    (currently 0.3s) must paint NOTHING — no flicker for quick turns.
    This is the load-bearing UX guarantee against an "indicator
    appears and immediately vanishes" effect."""
    fake = _FakeStderr(is_tty=True)
    monkeypatch.setattr(sys, "stderr", fake)
    monkeypatch.delenv("MONITOR_FORCE_PROGRESS", raising=False)

    with progress_dots("brief", interval=0.01):
        # Well under the 0.3s initial-delay threshold.
        time.sleep(0.05)

    # Nothing painted means no erase needed either: total output is empty.
    assert fake.getvalue() == ""


# ---------------------------------------------------------------------------
# MONITOR_FORCE_PROGRESS escape hatch
# ---------------------------------------------------------------------------


def test_force_progress_overrides_non_tty(monkeypatch):
    """MONITOR_FORCE_PROGRESS=1 must paint the spinner even when stderr
    isn't a TTY — escape hatch for debugging the indicator without
    needing an interactive shell."""
    fake = _FakeStderr(is_tty=False)
    monkeypatch.setattr(sys, "stderr", fake)
    monkeypatch.setenv("MONITOR_FORCE_PROGRESS", "1")

    with progress_dots("forced", interval=0.01):
        time.sleep(0.5)

    out = fake.getvalue()
    assert "forced" in out
    assert any(ch in out for ch in _SPINNER_FRAMES)


def test_force_progress_empty_string_does_not_override(monkeypatch):
    """The check is ``bool(os.getenv(...))``, so empty-string is
    falsy — must not activate the override. This guards against
    accidental ``MONITOR_FORCE_PROGRESS=`` (with no value) being
    interpreted as 'on'."""
    fake = _FakeStderr(is_tty=False)
    monkeypatch.setattr(sys, "stderr", fake)
    monkeypatch.setenv("MONITOR_FORCE_PROGRESS", "")

    with progress_dots("not-forced", interval=0.01):
        time.sleep(0.4)

    assert fake.getvalue() == ""


# ---------------------------------------------------------------------------
# Thread lifecycle
# ---------------------------------------------------------------------------


def test_animate_thread_joins_on_context_exit(monkeypatch):
    """The spinner thread must terminate cleanly when the context exits.
    A leaked thread holding stderr open would cause subtle output
    interleaving with subsequent prints."""
    fake = _FakeStderr(is_tty=True)
    monkeypatch.setattr(sys, "stderr", fake)
    monkeypatch.delenv("MONITOR_FORCE_PROGRESS", raising=False)

    pre_count = threading.active_count()

    with progress_dots("x", interval=0.01):
        time.sleep(0.4)
        mid_count = threading.active_count()

    # Give the daemon a beat to actually finish — the join inside the
    # context manager has a 2s cap, so by the time we get here it
    # should be done.
    time.sleep(0.1)
    post_count = threading.active_count()

    # Mid-operation: at least one extra thread (the animator).
    assert mid_count >= pre_count + 1
    # After exit: back to baseline (the animator joined and exited).
    assert post_count == pre_count


def test_exception_in_body_still_cleans_up(monkeypatch):
    """If the wrapped operation raises, the spinner thread must still
    be stopped and the indicator line erased — finally block guarantee."""
    fake = _FakeStderr(is_tty=True)
    monkeypatch.setattr(sys, "stderr", fake)
    monkeypatch.delenv("MONITOR_FORCE_PROGRESS", raising=False)

    pre_count = threading.active_count()

    with pytest.raises(RuntimeError, match="boom"):
        with progress_dots("x", interval=0.01):
            time.sleep(0.4)
            raise RuntimeError("boom")

    # Spinner thread must have joined despite the exception.
    time.sleep(0.1)
    assert threading.active_count() == pre_count
    # Erase-line sequence must still have been written.
    assert fake.getvalue().endswith("\r\033[2K")
