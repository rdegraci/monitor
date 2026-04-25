"""Tests for the isolated Monitor OOP history model and service."""
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.models import History, Message


def test_history_defaults_to_empty_messages() -> None:
    """Verify a new History starts with no messages."""

    history = History()

    assert history.snapshot() == []


def test_history_service_owns_history_instance() -> None:
    """Verify the history service owns a dedicated History object."""

    service = HistoryService(ConfigService())

    assert isinstance(service.history, History)
    assert service.snapshot() == []


def test_history_service_snapshot_after_mutations() -> None:
    """Verify history mutations update the snapshot."""

    service = HistoryService(ConfigService())
    first = Message(role="user", content="one")
    second = Message(role="assistant", content="two")
    third = Message(role="user", content="three")

    service.append(first)
    service.append(second)
    service.append(third)

    assert service.snapshot() == [first, second, third]

    service.trim(2)

    assert service.snapshot() == [second, third]

    service.clear()

    assert service.snapshot() == []

    service.reset_with_summary("summary text")

    snapshot = service.snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].role == "system"
    assert snapshot[0].content == "summary text"
