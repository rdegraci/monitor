"""Tests for the isolated Monitor OOP config service."""
import pytest

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.models import RuntimeConfig


def test_config_service_defaults() -> None:
    """Verify the default configuration service state."""

    service = ConfigService()

    assert service.get_model() == "gpt-5.4-mini"
    assert service.get_context_window() == 400_000
    assert service.get_provider() == "openai"


def test_config_service_select_model_rejects_empty_name() -> None:
    """Verify empty model names are rejected."""

    service = ConfigService()

    assert service.select_model("") is False
    assert service.get_model() == "gpt-5.4-mini"


def test_config_service_get_provider_from_prefixed_model_name() -> None:
    """Verify provider extraction from provider-prefixed model names."""

    service = ConfigService(initial_config=RuntimeConfig(full_model_name="anthropic/claude-3"))

    assert service.get_provider() == "anthropic"
    assert service.get_model() == "claude-3"
    assert service.get_full_model_name() == "anthropic/claude-3"
