"""Headless validation of the --tui spike (PLAN_MONITOR_TUI P0+P1+thin P2).

We can't run the full-screen app without a TTY, but the two hard points are
testable headlessly:
- P2: rich output is captured as ANSI.
- P1: the backend runs OFF the calling (UI) thread and its result is marshaled
  back via the loop callback.
- P0: the three-region Application constructs.
"""

import threading
import time

import pytest

from monitor.tui import spike


def test_run_and_capture_renders_rich_ansi(monkeypatch):
    monkeypatch.setattr(spike, "_TURN_DELAY", 0.0)
    out = spike._run_and_capture("xyz")
    assert "xyz" in out                 # content captured
    assert "you said" in out            # the stub backend's rich output
    assert "\x1b[" in out               # ANSI escapes → rich rendered to ANSI


def test_spikeapp_builds_three_regions():
    app = spike.SpikeApp()
    assert app.app is not None
    assert app._output_text() is not None          # output window content
    assert "tick" in app._info_text()              # info bar content
    assert app.input is not None                   # input area


def test_submit_runs_backend_off_thread_and_marshals_back(monkeypatch):
    monkeypatch.setattr(spike, "_TURN_DELAY", 0.0)
    app = spike.SpikeApp()

    # Fake loop: run scheduled callbacks inline, recording WHICH thread scheduled
    # them (must be the worker thread, never the test/UI thread).
    scheduling_threads = []

    class FakeLoop:
        def call_soon_threadsafe(self, fn, *a):
            scheduling_threads.append(threading.current_thread().name)
            fn(*a)

    app.loop = FakeLoop()
    app.app.invalidate = lambda: None  # app isn't running; no-op
    ui_thread = threading.current_thread().name

    app._submit("hello")  # dispatches to a worker thread

    deadline = time.time() + 3
    while app.processing and time.time() < deadline:
        time.sleep(0.01)

    assert app.processing is False                         # turn completed
    text = "".join(app._chunks)
    assert "you said" in text and "hello" in text          # result rendered into output
    # The backend dispatch came from the worker thread, not the UI thread.
    assert scheduling_threads and all(t != ui_thread for t in scheduling_threads)


def test_accept_handler_clears_input_and_submits(monkeypatch):
    monkeypatch.setattr(spike, "_TURN_DELAY", 0.0)
    app = spike.SpikeApp()
    app.loop = type("L", (), {"call_soon_threadsafe": staticmethod(lambda fn, *a: fn(*a))})()
    app.app.invalidate = lambda: None

    class Buff:
        text = "do a thing"

    keep = app._on_accept(Buff())
    assert keep is False  # input buffer is cleared
    deadline = time.time() + 3
    while app.processing and time.time() < deadline:
        time.sleep(0.01)
    assert "> do a thing" in "".join(app._chunks)  # echoed into output
