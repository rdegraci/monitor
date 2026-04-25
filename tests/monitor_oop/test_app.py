"""Tests for the isolated Monitor OOP app coordinator."""
from monitor_oop.core.app import build_app


def test_build_app_creates_runtime() -> None:
    """Verify the application factory returns a usable app."""

    app = build_app()

    assert app.context.config_service.get_model() == "default"
    assert app.context.history_service.messages == []
