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
    """Stub the backend hooks so __init__ does no real setup. compute_prompt_
    display returns a realistic multi-line status string (the shape
    format_prompt_display emits: leading blank, cwd, stats, prompt line)."""
    monkeypatch.setattr(
        tui_app, "prepare_chat_session", lambda: (object(), None)
    )
    monkeypatch.setattr(
        tui_app, "compute_prompt_display",
        lambda: "\n/home/u/proj\nC:12345 (80%) U:678 L:42 H:3\nmonitor gpt-5 medium ]] ",
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


def test_info_bar_shows_status_line_and_agents(stub_backend, monkeypatch):
    # No active agents → render_toolbar returns "".
    monkeypatch.setattr(
        "monitor.lib.agent_orchestrator.render_toolbar", lambda: ""
    )
    app = tui_app.MonitorTUI()
    bar = app._info_text()
    assert "C:12345 (80%)" in bar      # real status line (stats) rendered
    assert "H:3" in bar
    assert "agents — none" in bar       # no sub-agents
    assert "tick" in bar                # live tick still present
    # ANSI color codes from the status string are stripped for the reverse bar.
    assert "\x1b[" not in bar


def test_info_bar_shows_live_agent_status(stub_backend, monkeypatch):
    monkeypatch.setattr(
        "monitor.lib.agent_orchestrator.render_toolbar",
        lambda: "agents — a1b2: working",
    )
    app = tui_app.MonitorTUI()
    bar = app._info_text()
    assert "a1b2: working" in bar


def test_drain_agent_output_streams_into_window(stub_backend, monkeypatch):
    drained = [["[a1b2] tool: reading file", "[a1b2] ✓ found 3 matches"]]

    def fake_drain(limit=None):
        return drained.pop(0) if drained else []

    monkeypatch.setattr(
        "monitor.lib.agent_orchestrator.drain_pending_output", fake_drain
    )
    app = tui_app.MonitorTUI()
    app.loop = _FakeLoop()
    app.app.invalidate = lambda: None

    app._drain_agent_output()
    text = "".join(app._chunks)
    assert "[a1b2] tool: reading file" in text     # sub-agent stdout streamed
    assert "[a1b2] ✓ found 3 matches" in text       # sub-agent result streamed
    # Second drain is empty → nothing more appended.
    before = len(app._chunks)
    app._drain_agent_output()
    assert len(app._chunks) == before


def test_input_prompt_reflects_live_model(stub_backend, monkeypatch):
    monkeypatch.setattr(tui_app.config, "MODEL", "openai/gpt-5.4-mini", raising=False)
    app = tui_app.MonitorTUI()
    assert "openai/gpt-5.4-mini" in app._input_prompt()
    assert app._input_prompt().rstrip().endswith("]]")


def test_status_seeded_at_startup_and_recomputed(stub_backend):
    app = tui_app.MonitorTUI()
    assert app._status_line == "C:12345 (80%) U:678 L:42 H:3"  # stats line extracted


def test_emit_accumulates_and_renders(stub_backend):
    app = tui_app.MonitorTUI()
    app.loop = _FakeLoop()
    app.app.invalidate = lambda: None
    app._emit("\x1b[32mhello\x1b[0m")
    text = "".join(app._chunks)
    assert "hello" in text


def test_output_includes_scroll_to_bottom_marker(stub_backend):
    from prompt_toolkit.formatted_text import to_formatted_text

    app = tui_app.MonitorTUI()
    app._emit("line one\nline two\n")
    fragments = to_formatted_text(app._output_text())
    # The [SetCursorPosition] marker drives the Window's auto-follow scroll so
    # the newest output stays visible.
    assert any("[SetCursorPosition]" in style for style, _text, *_ in fragments)


def test_emit_trims_to_soft_cap(stub_backend, monkeypatch):
    monkeypatch.setattr(tui_app, "_MAX_OUTPUT_CHARS", 100)
    app = tui_app.MonitorTUI()
    app.loop = _FakeLoop()
    app.app.invalidate = lambda: None
    for _ in range(50):
        app._emit("x" * 20)
    total = sum(len(c) for c in app._chunks)
    assert total <= 100 + 20  # trimmed from the front, last chunk may overshoot


def test_sink_isatty_contract(stub_backend):
    """The spinner gates on sys.stderr.isatty(): stdout sink must be a tty (so
    rich/pygments colorize) and stderr sink must NOT (so the spinner suppresses
    under the TUI)."""
    app = tui_app.MonitorTUI()
    assert tui_app._OutputSink(app, tty=True).isatty() is True
    assert tui_app._OutputSink(app, tty=False).isatty() is False


def test_turn_captures_stdout_and_stderr_off_thread(stub_backend, monkeypatch):
    import sys

    ran_on = []

    def fake_process_input(text, history_file, session):
        ran_on.append(threading.current_thread().name)
        print(f"backend reply to {text!r}")          # stdout → output window
        print("a stderr diagnostic", file=sys.stderr) # stderr → output window
        # Under the TUI, stderr is a non-tty sink, so the spinner would suppress.
        assert sys.stderr.isatty() is False
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
    assert "a stderr diagnostic" in text                       # captured stderr
    # process_input ran on the worker thread, not the UI/test thread.
    assert ran_on and all(t != ui_thread for t in ran_on)
    # Backend output + the completion callback were marshaled FROM the worker
    # thread (the only UI-thread schedule is the pre-dispatch input echo).
    assert "tui-worker" in loop.scheduling_threads
    assert not app._exit_called                                # no :exit → app stays up


def test_input_wired_with_repl_lexer_completer_history(stub_backend):
    from monitor.lib.lexer import (
        RedAfter120Lexer, CommandCompleter, history as repl_history,
    )

    app = tui_app.MonitorTUI()
    # TextArea wraps lexer/completer in Dynamic* — unwrap to the real component.
    lexer = app.input.control.lexer
    lexer = lexer.get_lexer() if hasattr(lexer, "get_lexer") else lexer
    completer = app.input.buffer.completer
    completer = completer.get_completer() if hasattr(completer, "get_completer") else completer

    assert isinstance(lexer, RedAfter120Lexer)            # same lexer as the REPL
    assert isinstance(completer, CommandCompleter)        # :commands + path completion
    assert app.input.buffer.history is repl_history       # shared persistent history
    assert app.input.buffer.complete_while_typing() is False


def test_pipeline_mode_refused_without_nested_prompt(stub_backend, monkeypatch):
    submitted = []
    monkeypatch.setattr(tui_app.MonitorTUI, "_submit", lambda self, t: submitted.append(t))

    app = tui_app.MonitorTUI()
    app.app.invalidate = lambda: None

    class Buff:
        text = "| do a pipeline thing"

    keep = app._on_accept(Buff())
    assert keep is False
    assert submitted == []                                  # NOT dispatched (no nested prompt)
    assert "pipeline mode (|)" in "".join(app._chunks)      # friendly refusal shown


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


def test_main_configures_macros_and_builtins_before_launching_tui(monkeypatch):
    """Regression: --tui must launch AFTER configure_built_ins()/configure_macros()
    so macros ({{...}}) expand and built-ins/prompt-overrides are registered.
    (An earlier early-return dispatched the TUI before that setup.)"""
    import monitor.app as app_mod

    calls = []
    monkeypatch.setattr("sys.argv", ["monitor", "--tui"])
    for name in (
        "load_model_config", "load_environment_globals", "start_logging",
        "setup_sigint_handler", "configure_subsystems",
        "configure_runtime_prompt_paths", "configure_built_ins", "configure_macros",
    ):
        monkeypatch.setattr(app_mod, name, (lambda n: lambda *a, **k: calls.append(n))(name))
    monkeypatch.setattr("monitor.tui.app.run", lambda *a, **k: calls.append("run_tui"))

    app_mod.main()

    assert "run_tui" in calls                                       # TUI launched
    assert calls.index("configure_macros") < calls.index("run_tui")
    assert calls.index("configure_built_ins") < calls.index("run_tui")
    assert calls.index("configure_runtime_prompt_paths") < calls.index("run_tui")


def test_ctrl_c_does_not_quit_mid_turn(stub_backend):
    app = tui_app.MonitorTUI()
    app.app.invalidate = lambda: None
    app._exit_called = []
    app.app.exit = lambda *a, **k: app._exit_called.append(True)
    app.processing = True

    app._ctrl_c_action()
    assert app._exit_called == []                       # did NOT quit mid-turn
    assert "can't cancel it yet" in "".join(app._chunks)


def test_ctrl_c_clears_input_then_exits_when_idle(stub_backend):
    app = tui_app.MonitorTUI()
    app.app.invalidate = lambda: None
    app._exit_called = []
    app.app.exit = lambda *a, **k: app._exit_called.append(True)

    # Non-empty input → first Ctrl-C clears it, does not exit.
    app.input.buffer.text = "half-typed message"
    app._ctrl_c_action()
    assert app.input.buffer.text == ""
    assert app._exit_called == []

    # Empty input → Ctrl-C exits.
    app._ctrl_c_action()
    assert app._exit_called == [True]
    assert app._stop.is_set()


def test_model_switch_applied_after_turn(stub_backend, monkeypatch):
    calls = []

    def fake_switch(last_model):
        calls.append(last_model)
        return "new/model"   # simulate a :model switch having occurred

    monkeypatch.setattr(tui_app, "process_input", lambda t, h, s: False)
    monkeypatch.setattr(tui_app, "apply_model_switch_if_needed", fake_switch)
    monkeypatch.setattr(tui_app, "flush_logs_and_conversation", lambda: None)
    monkeypatch.setattr(tui_app, "_maybe_report_agent_result", lambda t: False)

    app = tui_app.MonitorTUI()
    _wire(app, _FakeLoop())
    app._last_model = "old/model"

    app._submit("switch the model")
    deadline = time.time() + 3
    while app.processing and time.time() < deadline:
        time.sleep(0.01)

    assert calls == ["old/model"]            # switch handler ran with prior model
    assert app._last_model == "new/model"    # tracked model updated


def test_turn_error_renders_without_crashing(stub_backend, monkeypatch):
    def boom(text, history_file, session):
        raise RuntimeError("backend exploded")

    monkeypatch.setattr(tui_app, "process_input", boom)
    monkeypatch.setattr(tui_app, "flush_logs_and_conversation", lambda: None)
    monkeypatch.setattr(tui_app, "_maybe_report_agent_result", lambda t: False)

    app = tui_app.MonitorTUI()
    _wire(app, _FakeLoop())

    app._submit("trigger error")
    deadline = time.time() + 3
    while app.processing and time.time() < deadline:
        time.sleep(0.01)

    assert app.processing is False                  # recovered, didn't hang
    assert "[error] turn failed" in "".join(app._chunks)
    assert not app._exit_called                     # error doesn't quit the app


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
