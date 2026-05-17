"""Tests for workflow helpers in Monitor OOP."""
from __future__ import annotations

from types import SimpleNamespace

from monitor_oop.core.workflow import reset_config
from monitor_oop.core.workflow import run_cli
from monitor_oop.core.workflow import run_script
from monitor_oop.core.workflow import run_server


class FakeSession:
    """Minimal session double for workflow tests."""

    def __init__(self) -> None:
        self.starts = 0

    def start(self) -> int:
        """Record and return a deterministic exit code."""

        self.starts += 1
        return 7

    def read_user_input(self):
        """Terminate the workflow loop."""

        raise EOFError

    def process_user_input(self, user_input):
        """Avoid extra output while matching the implementation contract."""

        return None


class FakeContext:
    """Minimal runtime context double for workflow tests."""

    def __init__(self, server_app=None) -> None:
        self.server_app = server_app
        self.config_service = SimpleNamespace(reset_called=False)

    def create_session(self):
        """Return a fake session."""

        return FakeSession()


class FakeApp:
    """Minimal app double for workflow tests."""

    def __init__(self, server_app=None) -> None:
        self.context = FakeContext(server_app=server_app)


def test_run_cli_uses_created_session() -> None:
    """Verify the CLI workflow runs the session returned by the app context."""

    app = FakeApp()

    assert run_cli(app) == 7


def test_run_server_returns_failure_without_server_app() -> None:
    """Verify the server workflow fails cleanly when no server app is configured."""

    app = FakeApp(server_app=None)

    assert run_server(app) == 1


def test_run_script_delegates_to_cli() -> None:
    """Verify script workflow delegates to the CLI workflow path."""

    app = FakeApp()

    assert run_script(app, "script.py") == 7


def test_reset_config_invokes_config_service_reset() -> None:
    """Verify configuration resets are forwarded to the app context."""

    app = FakeApp()
    app.context.config_service.reset = lambda force=False: setattr(app.context.config_service, "reset_called", force)

    reset_config(app, force=True)

    assert app.context.config_service.reset_called is True
