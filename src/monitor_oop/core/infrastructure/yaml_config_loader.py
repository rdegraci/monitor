"""YAML configuration loading for Monitor OOP."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import appdirs
import yaml

from monitor_oop.core.models import DEFAULT_MODEL, RuntimeConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LoadedConfig:
    """Resolved configuration values loaded from YAML sources."""

    full_model_name: str
    context_window: int
    prompt_history_filename: str
    history_dir: str
    logging_level: int


class YamlConfigLoader:
    """Load and validate YAML configuration for Monitor OOP."""

    def __init__(self, app_name: str = "monitor") -> None:
        """Initialize the YAML configuration loader.

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
        candidate_paths = self._get_user_config_paths()
        logger.info("YAML config candidate paths: %s", candidate_paths)

        resolved_full_model_name = DEFAULT_MODEL
        logger.info("Using default full_model_name: %s", resolved_full_model_name)
        resolved_context_window = RuntimeConfig(
            full_model_name=DEFAULT_MODEL
        ).context_window
        logger.info("Using default context_window: %s", resolved_context_window)
        resolved_logging_level = logging.INFO
        logger.info("Using default logging_level: %s", resolved_logging_level)
        resolved_prompt_history_filename = RuntimeConfig(
            full_model_name=DEFAULT_MODEL
        ).prompt_history_filename
        logger.info(
            "Using default prompt_history_filename: %s",
            resolved_prompt_history_filename,
        )
        resolved_history_dir = RuntimeConfig(full_model_name=DEFAULT_MODEL).history_dir
        logger.info("Using default history_dir: %s", resolved_history_dir)

        for yaml_path in candidate_paths:
            yaml_values = self._load_yaml_values(yaml_path)
            logger.info("Loaded YAML file %s with raw mapping: %s", yaml_path, yaml_values)
            if "model" in yaml_values and yaml_values["model"] is not None:
                resolved_full_model_name = str(yaml_values["model"])
            else:
                logger.info(
                    "Using default full_model_name from current resolution: %s",
                    resolved_full_model_name,
                )
            if "context_window" in yaml_values and yaml_values["context_window"] is not None:
                resolved_context_window = self._coerce_int(
                    yaml_values["context_window"],
                    resolved_context_window,
                )
            else:
                logger.info(
                    "Using default context_window from current resolution: %s",
                    resolved_context_window,
                )
            if "logging_level" in yaml_values and yaml_values["logging_level"] is not None:
                resolved_logging_level = self._coerce_int(
                    yaml_values["logging_level"], resolved_logging_level
                )
            else:
                logger.info(
                    "Using default logging_level from current resolution: %s",
                    resolved_logging_level,
                )
            if (
                "prompt_history_filename" in yaml_values
                and yaml_values["prompt_history_filename"] is not None
            ):
                resolved_prompt_history_filename = str(
                    yaml_values["prompt_history_filename"]
                )
            else:
                logger.info(
                    "Using default prompt_history_filename from current resolution: %s",
                    resolved_prompt_history_filename,
                )
            if "history_dir" in yaml_values and yaml_values["history_dir"] is not None:
                candidate_history_dir = yaml_values["history_dir"]
                if self._is_valid_history_dir(candidate_history_dir):
                    resolved_history_dir = str(candidate_history_dir)
                else:
                    resolved_history_dir = "history"
            else:
                logger.info(
                    "Using default history_dir from current resolution: %s",
                    resolved_history_dir,
                )

        resolved_config = LoadedConfig(
            full_model_name=resolved_full_model_name,
            context_window=resolved_context_window,
            prompt_history_filename=resolved_prompt_history_filename,
            history_dir=resolved_history_dir,
            logging_level=resolved_logging_level,
        )
        logger.info("Final resolved LoadedConfig values: %s", resolved_config)
        return resolved_config

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

    def _ensure_user_config_yaml(self) -> None:
        """Seed the user config YAML from the packaged example on first run."""

        config_dir = self._get_user_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        user_config_yaml_path = config_dir / "config.yaml"
        if user_config_yaml_path.exists():
            return

        packaged_example_path = Path(__file__).with_name("config.yaml.example")
        if packaged_example_path.exists():
            user_config_yaml_path.write_text(
                packaged_example_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

    def _load_yaml_values(self, yaml_path: str) -> dict[str, object]:
        """Load a YAML config file into a mapping."""

        if not os.path.exists(yaml_path):
            return {}

        with open(yaml_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}

        if not isinstance(data, dict):
            return {}

        return data

    def _coerce_int(self, value: object, default: int) -> int:
        """Coerce a value to int with a fallback default."""

        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _is_valid_history_dir(self, history_dir: object) -> bool:
        """Return whether a history directory value is valid."""

        return isinstance(history_dir, str) and bool(history_dir.strip())
