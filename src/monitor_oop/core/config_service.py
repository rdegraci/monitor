"""Isolated configuration service for Monitor OOP."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import appdirs
import yaml
from dotenv import dotenv_values, find_dotenv, load_dotenv

from .models import DEFAULT_MODEL, RuntimeConfig


class ConfigService:
    """Owns runtime configuration for a single application instance."""

    def __init__(self, initial_config: RuntimeConfig | None = None) -> None:
        self._config = initial_config or RuntimeConfig(model_name=DEFAULT_MODEL)
        self._openai_api_key = os.environ.get("OPENAI_API_KEY")
        self._logging_level = logging.INFO

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

    def _get_user_config_dir(self) -> Path:
        """Return the user configuration directory for Monitor."""

        return Path(appdirs.user_config_dir("monitor"))

    def _get_user_env_paths(self) -> list[str]:
        """Return candidate user .env paths in lookup order."""

        config_dir = self._get_user_config_dir()
        return [str(config_dir / ".env"), os.path.expanduser("~/.config/monitor/.env")]

    def _get_user_config_paths(self) -> list[str]:
        """Return candidate user config.yaml paths in lookup order."""

        config_dir = self._get_user_config_dir()
        return [
            str(config_dir / "config.yaml"),
            os.path.expanduser("~/.config/monitor/config.yaml"),
        ]

    def _ensure_user_config_yaml(self) -> str | None:
        """Create the user config.yaml from the example file on first run."""

        config_dir = self._get_user_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)

        user_config_path = config_dir / "config.yaml"
        if user_config_path.exists():
            return str(user_config_path)

        example_path = Path(__file__).with_name("config.yaml.example")
        if example_path.exists():
            user_config_path.write_text(
                example_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            return str(user_config_path)

        return None

    def _load_yaml_values(self, yaml_path: str | None) -> dict[str, object]:
        """Load configuration values from a YAML file."""

        if not yaml_path or not os.path.exists(yaml_path):
            return {}

        with open(yaml_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}

        if not isinstance(data, dict):
            return {}

        return data

    def _coerce_int(self, value: object, default: int) -> int:
        """Coerce a configuration value to int with a safe default."""

        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _is_valid_history_dir(self, history_dir: object) -> bool:
        """Return True when history_dir is a safe relative path segment."""

        if not isinstance(history_dir, str) or not history_dir.strip():
            return False

        path = Path(history_dir)
        return not path.is_absolute() and path.parts not in ((), ("..",))

    def _load_config_yaml(self) -> None:
        """Load YAML configuration using defaults first, then user files."""

        self._ensure_user_config_yaml()
        resolved_model = DEFAULT_MODEL
        resolved_context_window = RuntimeConfig(model_name=DEFAULT_MODEL).context_window
        resolved_logging_level = logging.INFO
        resolved_prompt_history_filename = RuntimeConfig(
            model_name=DEFAULT_MODEL
        ).prompt_history_filename
        resolved_history_dir = RuntimeConfig(model_name=DEFAULT_MODEL).history_dir

        for yaml_path in self._get_user_config_paths():
            yaml_values = self._load_yaml_values(yaml_path)
            if "model" in yaml_values and yaml_values["model"] is not None:
                resolved_model = str(yaml_values["model"])
            if "context_window" in yaml_values and yaml_values["context_window"] is not None:
                resolved_context_window = self._coerce_int(
                    yaml_values["context_window"],
                    resolved_context_window,
                )
            if "logging_level" in yaml_values and yaml_values["logging_level"] is not None:
                resolved_logging_level = self._coerce_int(
                    yaml_values["logging_level"], resolved_logging_level
                )
            if (
                "prompt_history_filename" in yaml_values
                and yaml_values["prompt_history_filename"] is not None
            ):
                resolved_prompt_history_filename = str(
                    yaml_values["prompt_history_filename"]
                )
            if "history_dir" in yaml_values and yaml_values["history_dir"] is not None:
                candidate_history_dir = yaml_values["history_dir"]
                if self._is_valid_history_dir(candidate_history_dir):
                    resolved_history_dir = str(candidate_history_dir)
                else:
                    resolved_history_dir = "history"

        self._config.model_name = resolved_model
        self._config.context_window = resolved_context_window
        self._config.prompt_history_filename = resolved_prompt_history_filename
        self._config.history_dir = resolved_history_dir
        self._logging_level = resolved_logging_level

    def _load_env(self) -> None:
        """Load dotenv files in deterministic precedence order."""

        project_env_path = find_dotenv(usecwd=True)
        if project_env_path:
            load_dotenv(project_env_path, override=True)

        user_env_path = os.path.join(appdirs.user_config_dir("monitor"), ".env")
        if os.path.exists(user_env_path):
            load_dotenv(user_env_path, override=True)

        fallback_env_path = os.path.expanduser("~/.config/monitor/.env")
        if fallback_env_path != user_env_path and os.path.exists(fallback_env_path):
            load_dotenv(fallback_env_path, override=True)

    def _apply_environment_overrides(self) -> None:
        """Apply environment variable overrides to the resolved configuration."""

        env_model = os.environ.get("MODEL")
        if env_model:
            self._config.model_name = env_model

        env_context_window = os.environ.get("CONTEXT_WINDOW")
        if env_context_window:
            self._config.context_window = self._coerce_int(
                env_context_window, self._config.context_window
            )

        env_logging_level = os.environ.get("LOG_LEVEL")
        if env_logging_level:
            self._logging_level = self._coerce_int(env_logging_level, self._logging_level)

        env_openai_api_key = os.environ.get("OPENAI_API_KEY")
        if env_openai_api_key:
            self._openai_api_key = env_openai_api_key
        elif self._openai_api_key:
            os.environ["OPENAI_API_KEY"] = self._openai_api_key

    def reset(self, force: bool = False) -> None:
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
