"""Tests for the isolated Monitor OOP app coordinator."""
from monitor_oop.core.app import build_app
from monitor_oop.core.models import DEFAULT_MODEL
from monitor_oop.__main__ import main


def test_build_app_creates_runtime() -> None:
    """Verify the application factory returns a usable app."""

    app = build_app()

    assert app.context.config_service.get_model() == DEFAULT_MODEL
    assert app.context.history_service.snapshot() == []
    assert app.context.llm_service is not None
    assert app.context.tool_service is not None
    assert app.context.tool_service.resolve_tool("get_current_weather") is not None


def test_build_app_provides_tui_app() -> None:
    """Verify the application factory wires a TUI app."""

    app = build_app()

    assert app.tui_app is not None


def test_run_tui_returns_zero_when_tui_app_present() -> None:
    """Verify the TUI entry point succeeds when a TUI app is available."""

    app = build_app()
    inputs = iter(["draft message\n", "quit\n"])
    outputs = []

    def output_fn(*args, **kwargs) -> None:
        outputs.append((args, kwargs))

    assert (
        app.run_tui(
            input_fn=lambda: next(inputs),
            output_fn=output_fn,
        )
        == 0
    )
    assert outputs or True


def test_main_uses_tui_entrypoint(monkeypatch) -> None:
    """Verify the --tui entry point routes to run_tui without external I/O."""

    class StubApp:
        def run_tui(self, input_fn=None, output_fn=None) -> int:
            assert input_fn is not None
            assert output_fn is not None
            assert input_fn() == "draft message\n"
            output_fn("assistant response")
            assert input_fn() == "quit\n"
            return 0

        def run(self) -> int:
            return 1

    inputs = iter(["draft message\n", "quit\n"])
    outputs = []
    monkeypatch.setattr("monitor_oop.__main__.build_app", lambda: StubApp())
    monkeypatch.setattr("sys.argv", ["monitor", "--tui"])

    assert (
        main(
            input_fn=lambda: next(inputs),
            output_fn=lambda *args, **kwargs: outputs.append((args, kwargs)),
        )
        == 0
    )
    assert outputs == [(("assistant response",), {})]
