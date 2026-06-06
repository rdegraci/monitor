"""Headless validation of the real --tui front-end (PLAN_MONITOR_TUI Phase 1).

The full-screen app can't run without a TTY, but the load-bearing mechanics are
testable headlessly:
- P0: the three-region Application constructs (backend setup stubbed).
- P1 (the crux): a submitted turn runs the REAL `process_input` OFF the UI
  thread, its stdout is captured into the output window, and completion is
  marshaled back via the loop callback.
- input is gated while a turn is in flight; `:exit` (exit_flag) exits the app.
"""

import threading
import time

import pytest

from monitor.tui import app as tui_app


@pytest.fixture
def stub_backend(monkeypatch):
    """Stub prepare_chat_session so __init__ does no real backend setup."""
    monkeypatch.setattr(
        tui_app, "prepare_chat_session", lambda: (object(), None)
    )


class _FakeLoop:
    """Runs scheduled callbacks inline, recording which thread scheduled them."""

    def __init__(self):
        self.scheduling_threads = []

    def call_soon_threadsafe(self, fn, *a):
        self.scheduling_threads.append(threading.current_thread().name)
        fn(*a)


def _wire(app, loop):
    """Attach a fake loop and neutralize the real Application's draw/exit."""
    app.loop = loop
    app.app.invalidate = lambda: None
    app._exit_called = []
    app.app.exit = lambda *a, **k: app._exit_called.append(True)


def test_builds_three_regions(stub_backend):
    app = tui_app.MonitorTUI()
    assert app.app is not None
    assert app._output_text() is not None          # output window content
    assert "tick" in app._info_text()              # info bar has the live tick
    assert app.input is not None                    # input area


def test_emit_accumulates_and_renders(stub_backend):
    app = tui_app.MonitorTUI()
    app.loop = _FakeLoop()
    app.app.invalidate = lambda: None
    app._emit("\x1b[32mhello\x1b[0m")
    text = "".join(app._chunks)
    assert "hello" in text


def test_emit_trims_to_soft_cap(stub_backend, monkeypatch):
    monkeypatch.setattr(tui_app, "_MAX_OUTPUT_CHARS", 100)
    app = tui_app.MonitorTUI()
    app.loop = _FakeLoop()
    app.app.invalidate = lambda: None
    for _ in range(50):
        app._emit("x" * 20)
    total = sum(len(c) for c in app._chunks)
    assert total <= 100 + 20  # trimmed from the front, last chunk may overshoot


def test_turn_runs_process_input_off_thread_and_captures_output(stub_backend, monkeypatch):
    ran_on = []

    def fake_process_input(text, history_file, session):
        ran_on.append(threading.current_thread().name)
        print(f"backend reply to {text!r}")   # goes through the redirected sink
        return False

    monkeypatch.setattr(tui_app, "process_input", fake_process_input)
    monkeypatch.setattr(tui_app, "flush_logs_and_conversation", lambda: None)
    monkeypatch.setattr(tui_app, "_maybe_report_agent_result", lambda t: False)

    app = tui_app.MonitorTUI()
    loop = _FakeLoop()
    _wire(app, loop)
    ui_thread = threading.current_thread().name

    app._submit("hello")

    deadline = time.time() + 3
    while app.processing and time.time() < deadline:
        time.sleep(0.01)

    assert app.processing is False                              # turn completed
    text = "".join(app._chunks)
    assert "> hello" in text                                   # echoed input
    assert "backend reply to 'hello'" in text                  # captured stdout
    # process_input ran on the worker thread, not the UI/test thread.
    assert ran_on and all(t != ui_thread for t in ran_on)
    # Backend output + the completion callback were marshaled FROM the worker
    # thread (the only UI-thread schedule is the pre-dispatch input echo).
    assert "tui-worker" in loop.scheduling_threads
    assert not app._exit_called                                # no :exit → app stays up


def test_input_gated_while_processing(stub_backend, monkeypatch):
    submitted = []
    monkeypatch.setattr(tui_app.MonitorTUI, "_submit", lambda self, t: submitted.append(t))

    app = tui_app.MonitorTUI()
    app.processing = True

    class Buff:
        text = "should be ignored"

    keep = app._on_accept(Buff())
    assert keep is False           # buffer still cleared
    assert submitted == []         # but no turn dispatched while processing


def test_exit_flag_exits_app(stub_backend, monkeypatch):
    monkeypatch.setattr(tui_app, "process_input", lambda t, h, s: True)  # :exit
    monkeypatch.setattr(tui_app, "flush_logs_and_conversation", lambda: None)
    monkeypatch.setattr(tui_app, "_maybe_report_agent_result", lambda t: False)

    app = tui_app.MonitorTUI()
    loop = _FakeLoop()
    _wire(app, loop)

    app._submit("exit")

    deadline = time.time() + 3
    while app.processing and time.time() < deadline:
        time.sleep(0.01)

    assert app.processing is False
    assert app._exit_called == [True]   # exit_flag → app.exit()
    assert app._stop.is_set()
