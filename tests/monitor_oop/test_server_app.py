"""Tests for the isolated Monitor OOP server app."""
from monitor_oop.core.command_processor import CommandProcessor
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.runtime_context import RuntimeContext
from monitor_oop.core.server_app import ServerApp
from monitor_oop.core.status_service import StatusService


def build_server_app() -> ServerApp:
    """Build a server app for tests."""

    config_service = ConfigService()
    history_service = HistoryService(config_service)
    macro_service = MacroService(config_service)
    status_service = StatusService()
    command_processor = CommandProcessor(config_service, history_service, macro_service, status_service)
    context = RuntimeContext(
        config_service=config_service,
        history_service=history_service,
        macro_service=macro_service,
        status_service=status_service,
        command_processor=command_processor,
    )
    return ServerApp(context)


def test_server_app_convert_messages_to_command() -> None:
    """Verify message conversion uses the last message content."""

    app = build_server_app()

    result = app.convert_messages_to_command([{"content": "first"}, {"content": "second"}])

    assert result == "second"
