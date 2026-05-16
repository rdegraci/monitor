"""Tests for configuration resolution behavior in Monitor OOP."""
from __future__ import annotations

from dataclasses import dataclass

from monitor_oop.core.config_resolution_service import ConfigResolutionService
from monitor_oop.core.models import RuntimeConfig


@dataclass
class LoadedYamlConfig:
    """Simple YAML config stub used for resolution tests."""

    full_model_name: str
    context_window: int
    output_window: int | None
    prompt_history_filename: str
    history_dir: str
    summarization_settings: object | None = None
    summarization: object | None = None


@dataclass
class LoadedModelConfigStub:
    """Simple model config stub used for resolution tests."""

    model_alias: str
    full_model_name: str
    context_window: int | None
    output_window: int | None
    conversation_turn_budget: int
    tokens_per_minute: int | None
    requests_per_minute: int | None
    provider: str


class ConfigLoaderStub:
    """Config loader stub that returns deterministic config values."""

    def __init__(self, yaml_config: LoadedYamlConfig, model_config: LoadedModelConfigStub) -> None:
        """Initialize the stub loader.

        Args:
            yaml_config: YAML configuration returned by the loader.
            model_config: Model configuration returned by the loader.
        """

        self.yaml_config = yaml_config
        self.model_config = model_config
        self.loaded_model_name: str | None = None

    def load_config_yaml(self) -> LoadedYamlConfig:
        """Return the configured YAML stub."""

        return self.yaml_config

    def load_model_config(self, model_name: str) -> LoadedModelConfigStub:
        """Return the configured model stub and record the requested model name."""

        self.loaded_model_name = model_name
        return self.model_config


def test_resolve_applies_yaml_values_before_model_values() -> None:
    """Verify resolution preserves YAML values that the model config does not override."""

    yaml_config = LoadedYamlConfig(
        full_model_name="openai/gpt-5.4-mini",
        context_window=123_456,
        output_window=7_890,
        prompt_history_filename="prompt_history",
        history_dir="history",
        summarization_settings={"token_limit": 1_000},
    )
    model_config = LoadedModelConfigStub(
        model_alias="gpt54mini",
        full_model_name="openai/gpt-5.4-mini",
        context_window=None,
        output_window=0,
        conversation_turn_budget=64,
        tokens_per_minute=2_500,
        requests_per_minute=25,
        provider="openai",
    )
    loader = ConfigLoaderStub(yaml_config, model_config)
    service = ConfigResolutionService(loader)
    config = RuntimeConfig(full_model_name="openai/gpt-5.4-mini")

    resolved = service.resolve(config)

    assert resolved is not config
    assert loader.loaded_model_name == "openai/gpt-5.4-mini"
    assert resolved.full_model_name == "openai/gpt-5.4-mini"
    assert resolved.context_window == 123_456
    assert resolved.output_window == 7_890
    assert resolved.prompt_history_filename == "prompt_history"
    assert resolved.history_dir == "history"
    assert resolved.summarization_settings == {"token_limit": 1_000}
    assert resolved.model_alias == "gpt54mini"
    assert resolved.conversation_turn_budget == 64
    assert resolved.tokens_per_minute == 2_500
    assert resolved.requests_per_minute == 25
    assert resolved.provider == "openai"


def test_resolve_prefers_model_window_values_when_present() -> None:
    """Verify non-zero model values override YAML-derived configuration."""

    yaml_config = LoadedYamlConfig(
        full_model_name="anthropic/claude-3",
        context_window=111,
        output_window=222,
        prompt_history_filename="prompt_history",
        history_dir="history",
    )
    model_config = LoadedModelConfigStub(
        model_alias="claude3",
        full_model_name="anthropic/claude-3",
        context_window=333,
        output_window=444,
        conversation_turn_budget=88,
        tokens_per_minute=555,
        requests_per_minute=666,
        provider="anthropic",
    )
    loader = ConfigLoaderStub(yaml_config, model_config)
    service = ConfigResolutionService(loader)
    config = RuntimeConfig(full_model_name="anthropic/claude-3")

    resolved = service.resolve(config)

    assert resolved.context_window == 333
    assert resolved.output_window == 444
    assert resolved.tokens_per_minute == 555
    assert resolved.requests_per_minute == 666
    assert resolved.conversation_turn_budget == 88
    assert resolved.provider == "anthropic"


def test_apply_loaded_model_config_returns_copy_and_keeps_original_config() -> None:
    """Verify model application works on a copy and leaves the original untouched."""

    yaml_config = LoadedYamlConfig(
        full_model_name="openai/gpt-5.4-mini",
        context_window=1,
        output_window=2,
        prompt_history_filename="prompt_history",
        history_dir="history",
    )
    model_config = LoadedModelConfigStub(
        model_alias="gpt54mini",
        full_model_name="openai/gpt-5.4-mini",
        context_window=3,
        output_window=4,
        conversation_turn_budget=5,
        tokens_per_minute=6,
        requests_per_minute=7,
        provider="openai",
    )
    loader = ConfigLoaderStub(yaml_config, model_config)
    service = ConfigResolutionService(loader)
    config = RuntimeConfig(full_model_name="openai/gpt-5.4-mini")

    yaml_applied = service._load_config_yaml(config)
    applied = service._apply_loaded_model_config(yaml_applied, model_config)

    assert applied is not yaml_applied
    assert config.context_window == 400_000
    assert yaml_applied.context_window == 1
    assert applied.context_window == 3
    assert applied.output_window == 4
    assert applied.model_alias == "gpt54mini"
    assert applied.provider == "openai"
