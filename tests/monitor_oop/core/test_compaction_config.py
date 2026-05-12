"""Tests for compaction-related runtime configuration."""
from __future__ import annotations

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.models import RuntimeConfig


def test_config_service_returns_compaction_runtime_configuration() -> None:
    """ConfigService should expose active compaction-related runtime settings."""

    runtime_config = RuntimeConfig()
    runtime_config.summarization.prompt_template = "Summary template"
    service = ConfigService(initial_config=runtime_config)

    assert service.get_summarization_prompt_template() == "Summary template"
    assert service.get_conversation_turn_budget() == runtime_config.conversation_max_turns
