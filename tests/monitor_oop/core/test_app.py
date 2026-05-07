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

    assert app.run_tui() == 0


def test_main_uses_tui_entrypoint(monkeypatch) -> None:
    """Verify the --tui entry point routes to run_tui without external I/O."""

    class StubApp:
        def run_tui(self) -> int:
            return 0

        def run(self) -> int:
            return 1

    monkeypatch.setattr("monitor_oop.__main__.build_app", lambda: StubApp())
    monkeypatch.setattr("sys.argv", ["monitor", "--tui"])

    assert main() == 0
