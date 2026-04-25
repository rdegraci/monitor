"""Tests for the isolated Monitor OOP app coordinator."""
from monitor_oop.core.app import build_app
from monitor_oop.core.models import DEFAULT_MODEL


def test_build_app_creates_runtime() -> None:
    """Verify the application factory returns a usable app."""

    app = build_app()

    assert app.context.config_service.get_model() == DEFAULT_MODEL
    assert app.context.history_service.messages == []
    assert app.context.llm_service is not None
