"""Tests for the isolated Monitor OOP conversation session."""
from monitor_oop.core.command_processor import CommandProcessor
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.conversation_session import ConversationSession
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.models import CommandType
from monitor_oop.core.runtime_context import RuntimeContext
from monitor_oop.core.status_service import StatusService


def build_session() -> ConversationSession:
    """Build a conversation session for tests."""

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
    return ConversationSession(context)


def test_conversation_session_start_sets_running() -> None:
    """Verify session start updates state."""

    session = build_session()

    assert session.start() == 0
    assert session.running is True
    assert session.context.state.running is True


def test_conversation_session_process_exit_command() -> None:
    """Verify exit commands stop the session."""

    session = build_session()
    session.start()

    assert session.process_user_input(":exit") is False
    assert session.running is False
    assert session.context.state.running is False
