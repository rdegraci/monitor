"""YAML configuration loading for Monitor OOP."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import appdirs
import yaml

from monitor_oop.core.models import DEFAULT_MODEL, RuntimeConfig


@dataclass(slots=True)
class LoadedConfig:
    """Resolved configuration values loaded from YAML sources."""

    model_name: str
    context_window: int
    prompt_history_filename: str
    history_dir: str
    logging_level: int


class ConfigLoader:
    """Load and validate YAML configuration for Monitor OOP."""

    def __init__(self, app_name: str = "monitor") -> None:
        """Initialize the configuration loader.

        Args:
            app_name: Application name used to resolve user config directories.
        """

        self._app_name = app_name

    def load_config_yaml(self) -> LoadedConfig:
        """Load YAML configuration using defaults first, then user files.

        Returns:
            The resolved configuration values.
        """

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

        return LoadedConfig(
            model_name=resolved_model,
            context_window=resolved_context_window,
            prompt_history_filename=resolved_prompt_history_filename,
            history_dir=resolved_history_dir,
            logging_level=resolved_logging_level,
        )

    def _get_user_config_dir(self) -> Path:
        """Return the user configuration directory for Monitor."""

        return Path(appdirs.user_config_dir(self._app_name))

    def _get_user_config_paths(self) -> list[str]:
        """Return candidate user config.yaml paths in lookup order."""

        config_dir = self._get_user_config_dir()
        return [
            str(config_dir / "config.yaml"),
            os.path.expanduser("~/.config/monitor/config.yaml"),
        ]

    def _ensure_user_config_yaml(self) -> str | None:
        """Create the user config.yaml from the example file on first run.

        Returns:
            The user config path when available, otherwise None.
        """

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
        """Load configuration values from a YAML file.

        Args:
            yaml_path: Path to the YAML file.

        Returns:
            Parsed YAML data or an empty mapping when unavailable.
        """

        if not yaml_path or not os.path.exists(yaml_path):
            return {}

        with open(yaml_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}

        if not isinstance(data, dict):
            return {}

        return data

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

    def _is_valid_history_dir(self, history_dir: object) -> bool:
        """Return True when history_dir is a safe relative path segment.

        Args:
            history_dir: Candidate history directory value.

        Returns:
            True when the directory is safe to use.
        """

        if not isinstance(history_dir, str) or not history_dir.strip():
            return False

        path = Path(history_dir)
        return not path.is_absolute() and path.parts not in ((), ("..",))
