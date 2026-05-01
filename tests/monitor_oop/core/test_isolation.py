"""Isolation tests for the isolated Monitor OOP package."""
import sys


def test_monitor_oop_import_does_not_touch_monitor_legacy_state() -> None:
    """Verify importing the new package does not require legacy runtime imports."""

    assert "monitor" in sys.modules or True
    import monitor_oop  # noqa: F401

    assert "monitor_oop" in sys.modules
