"""Model configuration resolution for Monitor OOP."""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

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
        self._log_yaml_config_values(config_values)
        self._apply_yaml_config_fields(resolved_config, config_values)
        self._log_yaml_application(resolved_config)
        return resolved_config

    def _load_model_config(self, config: RuntimeConfig) -> RuntimeConfig:
        """Load and apply model-specific configuration values.

        Args:
            config: Runtime config to update.

        Returns:
            The updated runtime config.
        """

        resolved_config = replace(config)
        model_name = resolved_config.full_model_name
        logger.info("Loading model config for %s", model_name)
        model_config = self._config_loader.load_model_config(model_name)
        self._log_model_config_values(model_name, model_config)
        self._apply_model_config_fields(resolved_config, model_config)
        self._log_model_application(resolved_config, model_config)
        return resolved_config

    def _apply_loaded_model_config(
        self, config: RuntimeConfig, model_config: LoadedModelConfig
    ) -> RuntimeConfig:
        """Apply loaded model values to the runtime config.

        Args:
            config: Runtime config to update.
            model_config: Loaded model-specific values.

        Returns:
            The updated runtime config.
        """

        resolved_config = replace(config)
        source_selection = self._apply_model_config_fields(resolved_config, model_config)
        logger.info(
            "Final runtime config source selection: %s",
            self._format_source_selection_summary(resolved_config, model_config, source_selection),
        )
        return resolved_config

    def _apply_yaml_config_fields(
        self, config: RuntimeConfig, config_values: Any
    ) -> RuntimeConfig:
        """Apply YAML-derived fields to a runtime config copy.

        Args:
            config: Runtime config to update.
            config_values: Loaded YAML configuration values.

        Returns:
            The updated runtime config.
        """

        config.full_model_name = config_values.full_model_name
        config.context_window = config_values.context_window
        config.output_window = getattr(config_values, "output_window", config.output_window)
        config.prompt_history_filename = config_values.prompt_history_filename
        config.history_dir = config_values.history_dir
        config.summarization_settings = getattr(
            config_values,
            "summarization_settings",
            getattr(config_values, "summarization", config.summarization_settings),
        )
        return config

    def _apply_model_config_fields(
        self, config: RuntimeConfig, model_config: LoadedModelConfig
    ) -> dict[str, tuple[Any, Any]]:
        """Apply model-derived fields to a runtime config copy.

        Args:
            config: Runtime config to update.
            model_config: Loaded model-specific values.

        Returns:
            A source-selection mapping for logged fields.
        """

        config.model_alias = model_config.model_alias
        config.full_model_name = model_config.full_model_name
        config.provider = model_config.provider

        source_selection: dict[str, tuple[Any, Any]] = {}

        yaml_context_window = config.context_window
        if model_config.context_window not in (None, 0):
            config.context_window = model_config.context_window
            source_selection["context_window"] = (yaml_context_window, "model")
        else:
            source_selection["context_window"] = (yaml_context_window, "yaml")

        yaml_output_window = config.output_window
        if model_config.output_window not in (None, 0):
            config.output_window = model_config.output_window
            source_selection["output_window"] = (yaml_output_window, "model")
        else:
            source_selection["output_window"] = (yaml_output_window, "yaml")

        yaml_tokens_per_minute = config.tokens_per_minute
        if model_config.tokens_per_minute not in (None, 0):
            config.tokens_per_minute = model_config.tokens_per_minute
            source_selection["tokens_per_minute"] = (yaml_tokens_per_minute, "model")
        else:
            source_selection["tokens_per_minute"] = (yaml_tokens_per_minute, "yaml")

        yaml_requests_per_minute = config.requests_per_minute
        if model_config.requests_per_minute not in (None, 0):
            config.requests_per_minute = model_config.requests_per_minute
            source_selection["requests_per_minute"] = (yaml_requests_per_minute, "model")
        else:
            source_selection["requests_per_minute"] = (yaml_requests_per_minute, "yaml")

        config.conversation_turn_budget = model_config.conversation_turn_budget
        return source_selection

    def _build_source_selection_summary(
        self, config: RuntimeConfig, model_config: LoadedModelConfig, source_selection: dict[str, tuple[Any, Any]]
    ) -> str:
        """Build a concise summary for source selection logging."""

        return (
            "context_window=%s (source=%s yaml=%s model=%s) "
            "output_window=%s (source=%s yaml=%s model=%s) "
            "tokens_per_minute=%s (source=%s yaml=%s model=%s) "
            "requests_per_minute=%s (source=%s yaml=%s model=%s) "
            "conversation_turn_budget=%s (model=%s)"
            % (
                config.context_window,
                source_selection["context_window"][1],
                source_selection["context_window"][0],
                model_config.context_window,
                config.output_window,
                source_selection["output_window"][1],
                source_selection["output_window"][0],
                model_config.output_window,
                config.tokens_per_minute,
                source_selection["tokens_per_minute"][1],
                source_selection["tokens_per_minute"][0],
                model_config.tokens_per_minute,
                config.requests_per_minute,
                source_selection["requests_per_minute"][1],
                source_selection["requests_per_minute"][0],
                model_config.requests_per_minute,
                config.conversation_turn_budget,
                model_config.conversation_turn_budget,
            )
        )

    def _log_yaml_config_values(self, config_values: Any) -> None:
        logger.info(
            "Loaded YAML-derived config values: full_model_name=%s context_window=%s output_window=%s prompt_history_filename=%s history_dir=%s summarization_settings=%s",
            config_values.full_model_name,
            config_values.context_window,
            getattr(config_values, "output_window", None),
            config_values.prompt_history_filename,
            config_values.history_dir,
            getattr(
                config_values,
                "summarization_settings",
                getattr(config_values, "summarization", None),
            ),
        )
        logger.info(
            "Applying YAML-derived config fields to RuntimeConfig: full_model_name=%s context_window=%s output_window=%s prompt_history_filename=%s history_dir=%s summarization_settings=%s",
            config_values.full_model_name,
            config_values.context_window,
            getattr(config_values, "output_window", None),
            config_values.prompt_history_filename,
            config_values.history_dir,
            getattr(
                config_values,
                "summarization_settings",
                getattr(config_values, "summarization", None),
            ),
        )

    def _log_yaml_application(self, resolved_config: RuntimeConfig) -> None:
        logger.info(
            "Applied YAML-derived config to RuntimeConfig: full_model_name=%s context_window=%s output_window=%s prompt_history_filename=%s history_dir=%s summarization_settings=%s",
            resolved_config.full_model_name,
            resolved_config.context_window,
            resolved_config.output_window,
            resolved_config.prompt_history_filename,
            resolved_config.history_dir,
            resolved_config.summarization_settings,
        )
        logger.info(
            "RuntimeConfig after YAML load: full_model_name=%s context_window=%s output_window=%s conversation_turn_budget=%s tokens_per_minute=%s requests_per_minute=%s provider=%s",
            resolved_config.full_model_name,
            resolved_config.context_window,
            resolved_config.output_window,
            resolved_config.conversation_turn_budget,
            resolved_config.tokens_per_minute,
            resolved_config.requests_per_minute,
            resolved_config.provider,
        )

    def _log_model_config_values(
        self, model_name: str, model_config: LoadedModelConfig
    ) -> None:
        logger.info(
            "Resolved model config for %s: model_alias=%s full_model_name=%s context_window=%s output_window=%s conversation_turn_budget=%s tokens_per_minute=%s requests_per_minute=%s provider=%s",
            model_name,
            model_config.model_alias,
            model_config.full_model_name,
            model_config.context_window,
            model_config.output_window,
            model_config.conversation_turn_budget,
            model_config.tokens_per_minute,
            model_config.requests_per_minute,
            model_config.provider,
        )
        logger.info(
            "Loaded model_config values before application: model_alias=%s full_model_name=%s context_window=%s output_window=%s conversation_turn_budget=%s tokens_per_minute=%s requests_per_minute=%s provider=%s",
            model_config.model_alias,
            model_config.full_model_name,
            model_config.context_window,
            model_config.output_window,
            model_config.conversation_turn_budget,
            model_config.tokens_per_minute,
            model_config.requests_per_minute,
            model_config.provider,
        )

    def _log_model_application(
        self, resolved_config: RuntimeConfig, model_config: LoadedModelConfig
    ) -> None:
        logger.info(
            "Applied model config to RuntimeConfig: full_model_name=%s model_alias=%s provider=%s context_window=%s output_window=%s conversation_turn_budget=%s tokens_per_minute=%s requests_per_minute=%s",
            resolved_config.full_model_name,
            resolved_config.model_alias,
            resolved_config.provider,
            resolved_config.context_window,
            resolved_config.output_window,
            resolved_config.conversation_turn_budget,
            resolved_config.tokens_per_minute,
            resolved_config.requests_per_minute,
        )
        logger.info(
            "RuntimeConfig after model config application: full_model_name=%s model_alias=%s context_window=%s output_window=%s conversation_turn_budget=%s tokens_per_minute=%s requests_per_minute=%s provider=%s",
            resolved_config.full_model_name,
            resolved_config.model_alias,
            resolved_config.context_window,
            resolved_config.output_window,
            resolved_config.conversation_turn_budget,
            resolved_config.tokens_per_minute,
            resolved_config.requests_per_minute,
            resolved_config.provider,
        )

    def _format_source_selection_summary(
        self,
        config: RuntimeConfig,
        model_config: LoadedModelConfig,
        source_selection: dict[str, tuple[Any, Any]],
    ) -> str:
        return self._build_source_selection_summary(config, model_config, source_selection)
