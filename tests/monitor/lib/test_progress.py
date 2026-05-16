import io
import sys
import time
import os

import pytest

from src.monitor.lib.progress import progress_dots


class _FakeStderr(io.StringIO):
    """A small StringIO that exposes isatty() for testing.

    Args:
        is_tty: Whether this fake stream should report itself as a TTY.
    """

    def __init__(self, is_tty: bool):
        super().__init__()
        self._is_tty = is_tty

    def isatty(self) -> bool:  # pragma: no cover - trivial wrapper
        return self._is_tty


def test_no_tty_no_force_prints_message_only(monkeypatch):
    """When stderr is not a TTY and MONITOR_FORCE_PROGRESS is not set, the
    context manager should print the message followed by a newline and should
    not start the dot-thread.
    """
    fake = _FakeStderr(is_tty=False)
    monkeypatch.setattr(sys, "stderr", fake)
    monkeypatch.delenv("MONITOR_FORCE_PROGRESS", raising=False)

    with progress_dots("hello", interval=0.01):
        # Exit immediately so no dots are produced.
        pass

    assert fake.getvalue() == "hello\n"


def test_tty_shows_dots_and_finishes_line(monkeypatch):
    """When stderr is a TTY the manager should print the message, emit dots
    while the context is active, and finish the line with a newline after
    exiting the context.
    """
    fake = _FakeStderr(is_tty=True)
    monkeypatch.setattr(sys, "stderr", fake)
    monkeypatch.delenv("MONITOR_FORCE_PROGRESS", raising=False)

    # Use a short interval and sleep inside the context so at least one dot is
    # printed; keep sleeps short to avoid test slowness.
    with progress_dots("msg", interval=0.01):
        time.sleep(0.05)

    out = fake.getvalue()
    assert out.startswith("msg")
    # At least one dot should have been printed.
    assert out.count(".") >= 1
    # Because we printed at least one dot, the implementation appends a newline
    # when the context exits.
    assert out.endswith("\n")


def test_force_progress_in_non_tty(monkeypatch):
    """Setting MONITOR_FORCE_PROGRESS forces the progress dots to run even if
    stderr.isatty() is False.
    """
    fake = _FakeStderr(is_tty=False)
    monkeypatch.setattr(sys, "stderr", fake)
    monkeypatch.setenv("MONITOR_FORCE_PROGRESS", "1")

    with progress_dots("forced", interval=0.01):
        time.sleep(0.05)

    out = fake.getvalue()
    assert out.startswith("forced")
    assert out.count(".") >= 1
    assert out.endswith("\n")
