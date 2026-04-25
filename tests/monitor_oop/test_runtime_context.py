"""Tests for the isolated Monitor OOP runtime context."""
from monitor_oop.core.command_processor import CommandProcessor
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.runtime_context import RuntimeContext
from monitor_oop.core.status_service import StatusService


def test_runtime_context_create_session() -> None:
    """Verify runtime context creates a conversation session."""

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

    session = context.create_session()

    assert session.context is context
    assert context.state.running is False
