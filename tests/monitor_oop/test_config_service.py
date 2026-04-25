"""Tests for the isolated Monitor OOP config service."""
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.models import RuntimeConfig


def test_config_service_defaults() -> None:
    """Verify the default configuration service state."""

    service = ConfigService()

    assert service.get_model() == "default"
    assert service.get_context_window() == 4_096


def test_config_service_select_model_updates_state() -> None:
    """Verify model selection updates the runtime config."""

    service = ConfigService(initial_config=RuntimeConfig(model_name="base"))

    assert service.select_model("gpt-4") is True
    assert service.get_model() == "gpt-4"


def test_config_service_select_model_rejects_empty_name() -> None:
    """Verify empty model names are rejected."""

    service = ConfigService()

    assert service.select_model("") is False
    assert service.get_model() == "default"
