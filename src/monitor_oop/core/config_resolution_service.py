"""Model configuration resolution for Monitor OOP."""
from __future__ import annotations

import logging
from dataclasses import replace

from monitor_oop.core.infrastructure.config_loader import ConfigLoader
from monitor_oop.core.infrastructure.model_config_loader import LoadedModelConfig
from monitor_oop.core.models import RuntimeConfig

logger = logging.getLogger(__name__)


class ConfigResolutionService:
    """Load and apply runtime configuration sources."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        """Initialize the resolution service.

        Args:
            config_loader: Optional loader dependency for testing.
        """

        self._config_loader = config_loader or ConfigLoader()

    def resolve(self, config: RuntimeConfig) -> RuntimeConfig:
        """Resolve YAML and model configuration into a copy of the runtime config."""

        resolved_config = replace(config)
        resolved_config = self._load_config_yaml(resolved_config)
        resolved_config = self._load_model_config(resolved_config)
        return resolved_config

    def _load_config_yaml(self, config: RuntimeConfig) -> RuntimeConfig:
        """Apply YAML configuration values to the runtime config.

        Args:
            config: Runtime config to update.

        Returns:
            The updated runtime config.
        """

        resolved_config = replace(config)
        config_values = self._config_loader.load_config_yaml()
        resolved_config.model_name = config_values.model_name
        resolved_config.context_window = config_values.context_window
        resolved_config.output_window = getattr(
            config_values, "output_window", resolved_config.output_window
        )
        resolved_config.prompt_history_filename = config_values.prompt_history_filename
        resolved_config.history_dir = config_values.history_dir
        resolved_config.summarization_settings = getattr(
            config_values,
            "summarization_settings",
            getattr(config_values, "summarization", resolved_config.summarization_settings),
        )
        return resolved_config

    def _load_model_config(self, config: RuntimeConfig) -> RuntimeConfig:
        """Load and apply model-specific configuration values.

        Args:
            config: Runtime config to update.

        Returns:
            The updated runtime config.
        """

        resolved_config = replace(config)
        model_name = resolved_config.model_name
        logger.info("Loading model config for %s", model_name)
        model_config = self._config_loader.load_model_config(model_name)
        logger.info(
            "Resolved model config for %s: model_alias=%s full_model_name=%s context_window=%s output_window=%s conversation_turn_budget=%s tokens_per_minute=%s requests_per_minute=%s",
            model_name,
            model_config.model_alias,
            model_config.full_model_name,
            model_config.context_window,
            model_config.output_window,
            model_config.conversation_turn_budget,
            model_config.tokens_per_minute,
            model_config.requests_per_minute,
        )
        return self._apply_loaded_model_config(resolved_config, model_config)

    def _apply_loaded_model_config(self, config: RuntimeConfig, model_config: LoadedModelConfig) -> RuntimeConfig:
        """Apply loaded model values to the runtime config.

        Args:
            config: Runtime config to update.
            model_config: Loaded model-specific values.

        Returns:
            The updated runtime config.
        """

        resolved_config = replace(config)
        resolved_config.model_alias = model_config.model_alias
        resolved_config.full_model_name = model_config.full_model_name
        resolved_config.provider = model_config.provider
        resolved_config.context_window = model_config.context_window
        resolved_config.output_window = model_config.output_window
        resolved_config.conversation_turn_budget = model_config.conversation_turn_budget
        resolved_config.tokens_per_minute = model_config.tokens_per_minute
        resolved_config.requests_per_minute = model_config.requests_per_minute
        resolved_model_name = model_config.model_alias or model_config.full_model_name
        if resolved_model_name:
            resolved_config.model_name = resolved_model_name
        return resolved_config
