"""Tests for the isolated Monitor OOP status service."""
from monitor_oop.core.status_service import StatusService


def test_status_service_transitions() -> None:
    """Verify status transitions between idle and working."""

    service = StatusService()

    assert service.get_state() == "idle"

    service.set_working()
    assert service.get_state() == "working"

    service.set_idle()
    assert service.get_state() == "idle"
