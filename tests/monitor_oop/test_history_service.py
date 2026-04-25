"""Tests for the isolated Monitor OOP history service."""
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.models import Message


def test_history_service_append_and_trim() -> None:
    """Verify history append and trim behavior."""

    service = HistoryService(ConfigService())
    service.append(Message(role="user", content="one"))
    service.append(Message(role="assistant", content="two"))
    service.append(Message(role="user", content="three"))

    service.trim(2)

    assert len(service.messages) == 2
    assert service.messages[0].content == "two"
    assert service.messages[1].content == "three"


def test_history_service_reset_with_summary() -> None:
    """Verify reset with summary seeds a system message."""

    service = HistoryService(ConfigService())

    service.reset_with_summary("summary text")

    assert len(service.messages) == 1
    assert service.messages[0].role == "system"
    assert service.messages[0].content == "summary text"
