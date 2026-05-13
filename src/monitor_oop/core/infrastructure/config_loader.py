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
        self._model_config_loader = ModelConfigLoader(app_name=app_name)

    def load_config_yaml(self) -> LoadedConfig:
        """Load YAML configuration using defaults first, then user files.

        Returns:
            The resolved configuration values.
        """

        return self._yaml_config_loader.load_config_yaml()

    def load_model_config(self, model_name: str) -> LoadedModelConfig:
        """Load model configuration from JSON schema data.

        Args:
            model_name: Active model alias to resolve.

        Returns:
            The resolved model configuration values.
        """

        resolved_model_name = model_name or DEFAULT_MODEL
        return self._model_config_loader.load_model_config(resolved_model_name)
