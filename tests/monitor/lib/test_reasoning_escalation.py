"""Tests for error-driven reasoning escalation helpers."""

from monitor.lib.reasoning_escalation import should_escalate


def test_should_escalate_below_high_levels() -> None:
    """Verify lower efforts still escalate to high on tool failure."""
    assert should_escalate("minimal") is True
    assert should_escalate("low") is True
    assert should_escalate("medium") is True


def test_should_not_escalate_high_or_above() -> None:
    """Verify high and xhigh efforts do not get overwritten."""
    assert should_escalate("high") is False
    assert should_escalate("xhigh") is False
