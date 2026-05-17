"""Tests for ResolvedRuntimeConfig in the Monitor OOP core layer."""
from __future__ import annotations

from monitor_oop.core.models import RuntimeConfig
from monitor_oop.core.resolved_runtime_config import ResolvedRuntimeConfig


def test_resolved_runtime_config_stores_values() -> None:
    """Verify the resolved runtime config stores the provided values unchanged."""

    config = RuntimeConfig(full_model_name="openai/gpt-4o")
    resolved = ResolvedRuntimeConfig(
        config=config,
        logging_level=20,
        openai_api_key="secret-key",
    )

    assert resolved.config is config
    assert resolved.logging_level == 20
    assert resolved.openai_api_key == "secret-key"
