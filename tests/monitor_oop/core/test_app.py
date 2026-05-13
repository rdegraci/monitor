"""Tests for the isolated Monitor OOP app coordinator."""

from monitor_oop.__main__ import main


def test_main_uses_tui_entrypoint(monkeypatch) -> None:
    """Verify the --tui entry point routes to the TUI path."""

    run_calls = []

    class StubApp:
        def run_tui(self) -> int:
            run_calls.append("run_tui")
            return 0

        def run(self) -> int:
            return 1

    monkeypatch.setattr("monitor_oop.__main__.build_app", lambda *args, **kwargs: StubApp())
    monkeypatch.setattr("sys.argv", ["monitor", "--tui"])

    assert main() == 0
    assert run_calls == ["run_tui"]
