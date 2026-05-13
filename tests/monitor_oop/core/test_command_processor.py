"""Tests for the isolated Monitor OOP command processor."""
from monitor_oop.core.command_processor import CommandProcessor
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.infrastructure.macro_store import MacroStore
from monitor_oop.core.infrastructure.macro_expander import MacroExpander
from monitor_oop.core.models import CommandType
from monitor_oop.core.status_service import StatusService


def build_processor() -> CommandProcessor:
    """Build a command processor for tests."""

    config_service = ConfigService()
    history_service = HistoryService(config_service)
    macro_store = MacroStore()
    macro_expander = MacroExpander()
    macro_service = MacroService(config_service, macro_store, macro_expander)
    status_service = StatusService()
    return CommandProcessor(config_service, history_service, macro_service, status_service)


def test_command_processor_evaluate_exit() -> None:
    """Verify exit commands are classified correctly."""

    processor = build_processor()

    result = processor.evaluate(":exit")

    assert result.command_type is CommandType.EXIT
    assert result.handled is True
