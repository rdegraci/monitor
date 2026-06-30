"""Compatibility wrapper for model config path resolution."""
from __future__ import annotations

import logging
from pathlib import Path

from monitor._stubs import appdirs

from monitor_oop.core.infrastructure.model_config_loader import ModelConfigLoader

logger = logging.getLogger(__name__)


class ModelConfigPathService(ModelConfigLoader):
    """Backward-compatible alias for model configuration path loading."""

    def __init__(self, app_name: str = "monitor") -> None:
        """Initialize the compatibility wrapper.

        Args:
            app_name: The application name used for config directory resolution.
        """
        super().__init__()
        self._app_name = app_name

    def get_user_config_path(self) -> Path:
        """Return the user-specific configuration file path.

        Returns:
            The path to the JSON configuration file for the configured application.
        """
        return Path(appdirs.user_config_dir(self._app_name, "monitor_oop")) / "model_config_v2.json"

    def load_json_config(self) -> dict[str, object]:
        """Load and return the parsed JSON configuration mapping.

        Returns:
            The parsed JSON configuration mapping for the configured application.
        """
        return self._load_model_config_data()
