"""Isolated configuration service for Monitor OOP."""
from __future__ import annotations

import os

import appdirs
from dotenv import dotenv_values, find_dotenv, load_dotenv

from .models import DEFAULT_MODEL, RuntimeConfig


class ConfigService:
    """Owns runtime configuration for a single application instance."""

    def __init__(self, initial_config: RuntimeConfig | None = None) -> None:
        self._config = initial_config or RuntimeConfig(model_name=DEFAULT_MODEL)
        self._openai_api_key = os.environ.get("OPENAI_API_KEY")

    def load(self) -> None:
        """Load configuration for the current process."""

        return None

    def _get_user_env_paths(self) -> list[str]:
        """Return candidate user configuration paths in lookup order."""

        config_dir = appdirs.user_config_dir("monitor")
        return [os.path.join(config_dir, ".env"), os.path.expanduser("~/.config/monitor/.env")]

    def _get_effective_openai_api_key(self, project_env_path: str, env_path: str) -> str | None:
        """Return the effective OPENAI_API_KEY from the environment or dotenv files."""

        existing_key = os.environ.get("OPENAI_API_KEY")
        if existing_key:
            return existing_key

        project_values = dotenv_values(project_env_path) if project_env_path else {}
        if project_values.get("OPENAI_API_KEY"):
            return project_values["OPENAI_API_KEY"]

        for user_env_path in self._get_user_env_paths():
            user_values = dotenv_values(user_env_path) if user_env_path and os.path.exists(user_env_path) else {}
            if user_values.get("OPENAI_API_KEY"):
                return user_values["OPENAI_API_KEY"]

        return None

    def load_env(self) -> None:
        """Load environment variables in legacy order.

        This first loads a project-level `.env` from the current working
        directory, if present, and then loads the Monitor user configuration
        `.env` file with override enabled. Missing files are ignored.
        """

        project_env_path = find_dotenv(usecwd=True)
        if project_env_path:
            load_dotenv(project_env_path)

        config_dir = appdirs.user_config_dir("monitor")
        env_path = os.path.join(config_dir, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)

        fallback_env_path = os.path.expanduser("~/.config/monitor/.env")
        if fallback_env_path != env_path and os.path.exists(fallback_env_path):
            load_dotenv(fallback_env_path, override=True)

        self._openai_api_key = self._get_effective_openai_api_key(project_env_path, env_path)
        if self._openai_api_key and not os.environ.get("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = self._openai_api_key

    def reset(self, force: bool = False) -> None:
        """Reset configuration to defaults."""

        self._config = RuntimeConfig(model_name=DEFAULT_MODEL)

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

    def get_openai_api_key(self) -> str | None:
        """Return the effective OPENAI_API_KEY for this runtime."""

        return self._openai_api_key
