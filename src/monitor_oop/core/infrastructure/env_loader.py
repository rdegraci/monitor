"""Environment configuration loading for Monitor OOP."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import appdirs
from dotenv import find_dotenv, load_dotenv

from ..models import RuntimeConfig


@dataclass(frozen=True)
class EnvOverrides:
    """Resolved environment overrides."""

    openai_api_key: str | None
    logging_level: int


class EnvLoader:
    """Load dotenv files and apply environment variable overrides."""

    def __init__(self, app_name: str = "monitor") -> None:
        """Initialize the environment loader.

        Args:
            app_name: Application name used to resolve user config directories.
        """

        self._app_name = app_name
        self._openai_api_key = os.environ.get("OPENAI_API_KEY")

    def load_env(self) -> None:
        """Load dotenv files in deterministic precedence order."""

        project_env_path = find_dotenv(usecwd=True)
        if project_env_path:
            load_dotenv(project_env_path, override=True)

        user_env_path = os.path.join(appdirs.user_config_dir(self._app_name), ".env")
        if os.path.exists(user_env_path):
            load_dotenv(user_env_path, override=True)

        fallback_env_path = os.path.expanduser("~/.config/monitor/.env")
        if fallback_env_path != user_env_path and os.path.exists(fallback_env_path):
            load_dotenv(fallback_env_path, override=True)

    def apply_environment_overrides(
        self,
        config: RuntimeConfig,
        current_openai_api_key: str | None = None,
    ) -> EnvOverrides:
        """Apply environment variable overrides to the resolved configuration.

        Args:
            config: Runtime config to update.
            current_openai_api_key: Existing API key value to preserve if needed.

        Returns:
            The resolved environment overrides.
        """

        env_model = os.environ.get("MODEL")
        if env_model:
            config.model_name = env_model

        env_context_window = os.environ.get("CONTEXT_WINDOW")
        if env_context_window:
            config.context_window = self._coerce_int(
                env_context_window,
                config.context_window,
            )

        env_logging_level = os.environ.get("LOG_LEVEL")
        logging_level = logging.INFO
        if env_logging_level:
            logging_level = self._coerce_int(env_logging_level, logging.INFO)

        env_openai_api_key = os.environ.get("OPENAI_API_KEY")
        if env_openai_api_key:
            self._openai_api_key = env_openai_api_key
        elif current_openai_api_key:
            self._openai_api_key = current_openai_api_key
            os.environ["OPENAI_API_KEY"] = current_openai_api_key

        return EnvOverrides(
            openai_api_key=self._openai_api_key,
            logging_level=logging_level,
        )

    def _coerce_int(self, value: object, default: int) -> int:
        """Coerce a configuration value to int with a safe default.

        Args:
            value: The value to coerce.
            default: Fallback value when coercion fails.

        Returns:
            The coerced integer or the default.
        """

        try:
            return int(value)
        except (TypeError, ValueError):
            return default
