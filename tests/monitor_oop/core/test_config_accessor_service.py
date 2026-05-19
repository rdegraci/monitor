"""Tests for ConfigAccessorService in the Monitor OOP core layer."""
from __future__ import annotations

from monitor_oop.core.config_accessor_service import ConfigAccessorService
from monitor_oop.core.models import RuntimeConfig


def test_accessor_returns_config_values() -> None:
    """Verify the service exposes the current runtime configuration values."""

    config = RuntimeConfig(
        full_model_name="openai/gpt-4o",
        context_window=123_456,
        output_window=7_890,
        conversation_turn_budget=42,
    )
    service = ConfigAccessorService(
        config=config,
        openai_api_key="api-key",
        logging_level=30,
    )

    assert service.get_model() == "gpt-4o"
    assert service.get_full_model_name() == "openai/gpt-4o"
    assert service.get_provider() == "openai"
    assert service.get_context_window() == 123_456
    assert service.get_output_window() == 7_890
    assert service.get_conversation_turn_budget() == 42
    assert service.get_openai_api_key() == "api-key"
    assert service.get_logging_level() == 30


def test_accessor_uses_config_provider_when_full_model_name_missing() -> None:
    """Verify provider falls back to the config provider when no full model name is present."""

    config = RuntimeConfig(full_model_name="fallback-model", provider="anthropic")
    service = ConfigAccessorService(config=config, openai_api_key=None, logging_level=20)

    assert service.get_provider() == "anthropic"


def test_accessor_reads_configured_rate_limits() -> None:
    """Verify TPM/RPM accessors read the canonical config fields directly."""

    config = RuntimeConfig(
        full_model_name="openai/gpt-4o",
        tokens_per_minute=111,
        requests_per_minute=222,
    )
    service = ConfigAccessorService(config=config, openai_api_key=None, logging_level=20)

    assert service.get_model_tpm_limit() == 111
    assert service.get_model_rpm_limit() == 222
    # model_name is accepted for API symmetry but ignored — per-model overrides
    # are not supported.
    assert service.get_model_tpm_limit("other/model") == 111
    assert service.get_model_rpm_limit("other/model") == 222


def test_accessor_treats_zero_rate_limit_as_disabled() -> None:
    """Verify explicit 0 for TPM/RPM is coerced to None (same as unset)."""

    config = RuntimeConfig(
        full_model_name="openai/gpt-4o",
        tokens_per_minute=0,
        requests_per_minute=0,
    )
    service = ConfigAccessorService(config=config, openai_api_key=None, logging_level=20)

    assert service.get_model_tpm_limit() is None
    assert service.get_model_rpm_limit() is None


def test_accessor_returns_none_when_rate_limits_unset() -> None:
    """Verify missing TPM/RPM fields surface as None."""

    config = RuntimeConfig(full_model_name="openai/gpt-4o")
    service = ConfigAccessorService(config=config, openai_api_key=None, logging_level=20)

    assert service.get_model_tpm_limit() is None
    assert service.get_model_rpm_limit() is None
