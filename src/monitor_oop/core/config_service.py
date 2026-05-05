"""Isolated configuration service for Monitor OOP."""
from __future__ import annotations

import appdirs
import logging
import os
from pathlib import Path

from monitor_oop.core.infrastructure.config_loader import ConfigLoader
from monitor_oop.core.infrastructure.env_loader import EnvLoader
from monitor_oop.core.models import DEFAULT_MODEL, RuntimeConfig


class ConfigService:
    """Owns runtime configuration for a single application instance."""

    def __init__(self, initial_config: RuntimeConfig | None = None) -> None:
        self._config = initial_config or RuntimeConfig(model_name=DEFAULT_MODEL)
        self._openai_api_key = os.environ.get("OPENAI_API_KEY")
        self._logging_level = logging.INFO
        self._config_loader = ConfigLoader()
        self._env_loader = EnvLoader()

    def load(self) -> None:
        """Load configuration for the current process."""

        self._apply_defaults()
        self._load_config_yaml()
        self._load_env()
        self._apply_environment_overrides()

    def load_env(self) -> None:
        """Load dotenv files and apply environment overrides."""

        self._load_env()
        self._apply_environment_overrides()

    def load_config_yaml(self) -> None:
        """Load YAML configuration using defaults first, then user files."""

        self._load_config_yaml()

    def _apply_defaults(self) -> None:
        """Reset the runtime configuration to deterministic defaults."""

        self._config = RuntimeConfig(model_name=DEFAULT_MODEL)
        self._logging_level = logging.INFO
        self._openai_api_key = os.environ.get("OPENAI_API_KEY")

    def _load_config_yaml(self) -> None:
        """Load YAML configuration using defaults first, then user files."""

        config_values = self._config_loader.load_config_yaml()
        self._config.model_name = config_values.model_name
        self._config.context_window = config_values.context_window
        self._config.prompt_history_filename = config_values.prompt_history_filename
        self._config.history_dir = config_values.history_dir
        self._logging_level = config_values.logging_level

    def _load_env(self) -> None:
        """Load dotenv files in deterministic precedence order."""

        self._env_loader.load_env()

    def _apply_environment_overrides(self) -> None:
        """Apply environment variable overrides to the resolved configuration."""

        env_values = self._env_loader.apply_environment_overrides(
            self._config,
            current_openai_api_key=self._openai_api_key,
        )
        self._openai_api_key = env_values.openai_api_key
        self._logging_level = env_values.logging_level

    def reset(self) -> None:
        """Reset configuration to defaults."""

        self._config = RuntimeConfig(model_name=DEFAULT_MODEL)
        self._logging_level = logging.INFO
        self._openai_api_key = os.environ.get("OPENAI_API_KEY")

    def select_model(self, model_name: str) -> bool:
        """Select the active model for this runtime."""

        if model_name:
            self._config.model_name = model_name
            return True
        return False

    def get_model(self) -> str:
        """Return the active model name."""

        return self._config.model_name

    def get_provider(self) -> str:
        """Return the provider prefix for the active model name."""

        model_name = self._config.model_name
        if "/" in model_name:
            return model_name.split("/", 1)[0]
        return "openai"

    def get_context_window(self) -> int:
        """Return the active context window size."""

        return self._config.context_window

    def _get_user_config_dir(self) -> Path:
        """Return the user configuration directory."""

        return Path(appdirs.user_config_dir("monitor"))

    def _ensure_history_dir(self, config_dir: Path) -> bool:
        """Ensure the history directory exists and is writable."""

        try:
            config_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False

        return os.access(config_dir, os.W_OK)

    def _get_history_file_path(self, base_dir: Path) -> str:
        """Return a writable prompt history file path rooted at base_dir."""

        history_dir = base_dir / self._config.history_dir
        if not self._ensure_history_dir(history_dir):
            return ""

        filename = self._config.prompt_history_filename or "prompt_history"
        history_path = history_dir / filename
        parent_dir = history_path.parent

        try:
            parent_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return ""

        if not os.access(parent_dir, os.W_OK):
            return ""

        return str(history_path)

    def _get_system_prompt_file_path(self, base_dir: Path) -> str:
        """Return a writable system prompt file path rooted at base_dir."""

        system_prompt_path = base_dir / "system_prompt"
        parent_dir = system_prompt_path.parent

        try:
            parent_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return ""

        if not os.access(parent_dir, os.W_OK):
            return ""

        return str(system_prompt_path)

    def get_persistent_history_file_path(self) -> str:
        """Return the first writable persistent history file path."""

        for candidate in (
            self._get_user_config_dir(),
            Path(os.path.expanduser("~/.config/monitor")),
        ):
            writable_path = self._get_history_file_path(candidate)
            if writable_path:
                return writable_path

        return ""

    def get_system_prompt_file_path(self) -> str:
        """Return the first writable system prompt file path."""

        for candidate in (
            self._get_user_config_dir(),
            Path(os.path.expanduser("~/.config/monitor")),
        ):
            writable_path = self._get_system_prompt_file_path(candidate)
            if writable_path:
                return writable_path

        return ""

    def get_history_file_path(self) -> str:
        """Return the persistent prompt history file path."""

        return self.get_persistent_history_file_path()

    def get_openai_api_key(self) -> str | None:
        """Return the effective OPENAI_API_KEY for this runtime."""

        return self._openai_api_key

    def get_logging_level(self) -> int:
        """Return the logging level from LOG_LEVEL with a safe INFO default.

        Returns:
            int: The resolved logging level constant.
        """

        return self._logging_level
