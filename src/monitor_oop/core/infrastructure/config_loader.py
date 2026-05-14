"""YAML configuration loading for Monitor OOP."""
from __future__ import annotations

import logging

from monitor_oop.core.models import DEFAULT_MODEL
from monitor_oop.core.infrastructure.model_config_loader import LoadedModelConfig, ModelConfigLoader
from monitor_oop.core.infrastructure.yaml_config_loader import LoadedConfig, YamlConfigLoader

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Load and validate configuration for Monitor OOP."""

    def __init__(self, app_name: str = "monitor") -> None:
        """Initialize the configuration loader.

        Args:
            app_name: Application name used to resolve user config directories.
        """

        self._yaml_config_loader = YamlConfigLoader(app_name=app_name)
        self._model_config_loader = ModelConfigLoader()

    def load_config_yaml(self) -> LoadedConfig:
        """Load YAML configuration using defaults first, then user files.

        Returns:
            The resolved configuration values.
        """

        logger.info("Requesting YAML config from YamlConfigLoader")
        config = self._yaml_config_loader.load_config_yaml()
        logger.info("Received YAML config from YamlConfigLoader: %r", config)
        return config

    def load_model_config(self, model_name: str) -> LoadedModelConfig:
        """Load model configuration from JSON schema data.

        Args:
            model_name: Active model alias to resolve.

        Returns:
            The resolved model configuration values.
        """

        resolved_model_name = model_name or DEFAULT_MODEL
        logger.info("Requesting model config from ModelConfigLoader for model_name=%r resolved_model_name=%r", model_name, resolved_model_name)
        config = self._model_config_loader.load_model_config(resolved_model_name)
        logger.info("Received model config from ModelConfigLoader for resolved_model_name=%r: %r", resolved_model_name, config)
        return config
