"""Tests for workflow helpers in Monitor OOP."""
from __future__ import annotations

from types import SimpleNamespace

from monitor_oop.core.infrastructure.rate_limit_service import RateLimitDeniedError
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


class _RateLimitDenyOnceSession:
    """Session double: denies once with a rate-limit error, then exits cleanly."""

    def __init__(self) -> None:
        self.start_called = False
        self.inputs_seen: list[str] = []
        self.process_calls = 0

    def start(self) -> int:
        self.start_called = True
        return 0

    def read_user_input(self) -> str:
        # First call returns a prompt; second call exits the loop.
        if not self.inputs_seen:
            self.inputs_seen.append("hello")
            return "hello"
        raise EOFError

    def process_user_input(self, user_input: str):
        self.process_calls += 1
        raise RateLimitDeniedError(
            reason="tpm",
            model="openai/gpt-4o",
            current=4_950,
            limit=5_000,
            retry_after_seconds=12.0,
        )


class _RateLimitDenyContext:
    server_app = None
    config_service = SimpleNamespace(reset_called=False)

    def __init__(self) -> None:
        self.session = _RateLimitDenyOnceSession()

    def create_session(self):
        return self.session


class _RateLimitDenyApp:
    def __init__(self) -> None:
        self.context = _RateLimitDenyContext()


def test_run_cli_prints_friendly_message_and_continues_on_rate_limit_denial(capsys) -> None:
    """Verify the REPL loop surfaces a RateLimitDeniedError to stdout and stays alive."""

    app = _RateLimitDenyApp()
    exit_code = run_cli(app)

    captured = capsys.readouterr()
    # The loop survived the denial (a second read_user_input was reached and
    # raised EOFError to terminate normally).
    assert exit_code == 0
    assert app.context.session.process_calls == 1
    # The denial detail is visible on stdout — including reason, current/limit
    # numbers, and the approximate retry-after window.
    assert "[rate limit]" in captured.out
    assert "Token-per-minute" in captured.out
    assert "4950/5000" in captured.out
    assert "12s" in captured.out
