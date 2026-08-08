"""YAML configuration loading for Monitor OOP."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path

from monitor._stubs import appdirs, yaml

from monitor_oop.core.models import DEFAULT_MODEL, RuntimeConfig, SummarizationSettings

logger = logging.getLogger(__name__)

_LOGGING_LEVEL_NAMES = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


@dataclass(slots=True)
class LoadedConfig:
    """Resolved configuration values loaded from YAML sources."""

    full_model_name: str
    context_window: int
    prompt_history_filename: str
    history_dir: str
    logging_level: int
    summarization_settings: SummarizationSettings


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
        resolved_summarization = SummarizationSettings()
        logger.info("Using default summarization_settings: %s", resolved_summarization)

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
                resolved_logging_level = self._coerce_logging_level(
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
            if "summarization" in yaml_values and yaml_values["summarization"] is not None:
                resolved_summarization = self._coerce_summarization_settings(
                    yaml_values["summarization"],
                    resolved_summarization,
                )
            else:
                logger.info(
                    "Using default summarization_settings from current resolution: %s",
                    resolved_summarization,
                )

        resolved_config = LoadedConfig(
            full_model_name=resolved_full_model_name,
            context_window=resolved_context_window,
            prompt_history_filename=resolved_prompt_history_filename,
            history_dir=resolved_history_dir,
            logging_level=resolved_logging_level,
            summarization_settings=resolved_summarization,
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

    def _coerce_logging_level(self, value: object, default: int) -> int:
        """Coerce a logging level from int or level name."""

        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            named = _LOGGING_LEVEL_NAMES.get(value.strip().upper())
            if named is not None:
                return named
            try:
                return int(value.strip())
            except ValueError:
                return default
        return default

    def _coerce_summarization_settings(
        self,
        value: object,
        default: SummarizationSettings,
    ) -> SummarizationSettings:
        """Build summarization settings from a YAML mapping."""

        if not isinstance(value, dict):
            return default

        token_limit = default.token_limit
        if "token_limit" in value and value["token_limit"] is not None:
            token_limit = self._coerce_int(value["token_limit"], default.token_limit)

        prompt_template = default.prompt_template
        if "prompt_template" in value and value["prompt_template"] is not None:
            prompt_template = str(value["prompt_template"])

        preserve_units = default.preserve_units
        if "preserve_units" in value and value["preserve_units"] is not None:
            preserve_units = self._coerce_int(value["preserve_units"], default.preserve_units)

        compaction_soft_ratio = default.compaction_soft_ratio
        if (
            "compaction_soft_ratio" in value
            and value["compaction_soft_ratio"] is not None
        ):
            try:
                compaction_soft_ratio = float(value["compaction_soft_ratio"])
            except (TypeError, ValueError):
                compaction_soft_ratio = default.compaction_soft_ratio

        return replace(
            default,
            token_limit=token_limit,
            prompt_template=prompt_template,
            preserve_units=preserve_units,
            compaction_soft_ratio=compaction_soft_ratio,
        )

    def _is_valid_history_dir(self, history_dir: object) -> bool:
        """Return whether a history directory value is valid."""

        return isinstance(history_dir, str) and bool(history_dir.strip())
