"""YAML configuration loading for Monitor OOP."""
from __future__ import annotations

import json
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

    model_name: str
    context_window: int
    prompt_history_filename: str
    history_dir: str
    logging_level: int


@dataclass(slots=True)
class LoadedModelConfig:
    """Resolved model configuration values loaded from JSON sources."""

    model_alias: str
    provider: str
    full_model_name: str
    context_window: int
    output_window: int
    conversation_turn_budget: int
    tokens_per_minute: int
    requests_per_minute: int


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

    def load_model_config(self, model_name: str) -> LoadedModelConfig:
        """Load model configuration from JSON schema data.

        Args:
            model_name: Active model alias to resolve.

        Returns:
            The resolved model configuration values.
        """

        user_model_config = self._load_model_config_json(self._get_user_model_config_path())
        packaged_model_config = self._load_model_config_json(self._get_packaged_model_config_path())

        resolved_alias = self._resolve_model_alias(
            model_name,
            user_model_config,
            packaged_model_config,
        )
        logger.info("Selected model %s resolved to alias %s", model_name, resolved_alias)
        resolved_full_model_name = model_name or DEFAULT_MODEL
        provider = self._resolve_provider(resolved_alias, user_model_config, packaged_model_config)
        conversation_turn_budget = self._resolve_conversation_turn_budget(
            resolved_alias,
            user_model_config,
            packaged_model_config,
        )
        context_window = self._resolve_int_mapping_value(
            resolved_alias,
            "context_window_mapping",
            user_model_config,
            packaged_model_config,
            0,
        )
        output_window = self._resolve_int_mapping_value(
            resolved_alias,
            "output_window_mapping",
            user_model_config,
            packaged_model_config,
            0,
        )
        tokens_per_minute = self._resolve_tokens_per_minute(
            resolved_alias,
            user_model_config,
            packaged_model_config,
        )

        return LoadedModelConfig(
            model_alias=resolved_alias,
            provider=provider,
            full_model_name=resolved_full_model_name,
            context_window=context_window,
            output_window=output_window,
            conversation_turn_budget=conversation_turn_budget,
            tokens_per_minute=tokens_per_minute,
            requests_per_minute=0,
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

    def _get_packaged_model_config_path(self) -> Path:
        """Return the packaged model_config_v2.json path."""

        return Path(__file__).with_name("model_config_v2.json")

    def _get_user_model_config_path(self) -> Path:
        """Return the user model_config_v2.json path."""

        return self._get_user_config_dir() / "model_config_v2.json"

    def _ensure_user_model_config_json(self) -> str | None:
        """Seed the user model config JSON from the packaged file on first run.

        Returns:
            The user model config path when available, otherwise None.
        """

        config_dir = self._get_user_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)

        user_model_config_path = self._get_user_model_config_path()
        if user_model_config_path.exists():
            return str(user_model_config_path)

        packaged_model_config_path = self._get_packaged_model_config_path()
        if packaged_model_config_path.exists():
            user_model_config_path.write_text(
                packaged_model_config_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            return str(user_model_config_path)

        return None

    def _load_model_config_json(self, json_path: Path) -> dict[str, object]:
        """Load a model config JSON file."""

        if not json_path.exists():
            return {}

        with open(json_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        if not isinstance(data, dict):
            return {}

        return data

    def _resolve_model_alias(
        self,
        model_name: str,
        user_model_config: dict[str, object],
        packaged_model_config: dict[str, object],
    ) -> str:
        """Resolve the model alias from a YAML-selected model string."""

        if not model_name:
            return DEFAULT_MODEL

        alias = self._find_model_alias(model_name, user_model_config)
        if alias is not None:
            return alias

        alias = self._find_model_alias(model_name, packaged_model_config)
        if alias is not None:
            return alias

        return model_name

    def _find_model_alias(self, model_name: str, model_config_data: dict[str, object]) -> str | None:
        """Return the alias for the given model name when present."""

        if not model_name or not isinstance(model_config_data, dict):
            return None

        mapping = model_config_data.get("model_mapping")
        if not isinstance(mapping, dict):
            return None

        value = mapping.get(model_name)
        if value is None:
            return None

        return str(value)

    def _resolve_provider(
        self,
        model_alias: str,
        user_model_config: dict[str, object],
        packaged_model_config: dict[str, object],
    ) -> str:
        """Resolve provider from model_tpm_mapping."""

        provider = self._resolve_mapping_string_value(
            model_alias,
            "model_tpm_mapping",
            user_model_config,
            packaged_model_config,
        )
        if provider:
            return provider

        if model_alias != DEFAULT_MODEL:
            provider = self._resolve_mapping_string_value(
                DEFAULT_MODEL,
                "model_tpm_mapping",
                user_model_config,
                packaged_model_config,
            )
            if provider:
                return provider

        return ""

    def _resolve_conversation_turn_budget(
        self,
        model_alias: str,
        user_model_config: dict[str, object],
        packaged_model_config: dict[str, object],
    ) -> int:
        """Resolve conversation turn budget from conversation_history_mapping."""

        for model_config in (user_model_config, packaged_model_config):
            mapping = model_config.get("conversation_history_mapping")
            if isinstance(mapping, dict):
                if model_alias in mapping:
                    candidate = mapping[model_alias]
                    if isinstance(candidate, int):
                        return candidate
                    if isinstance(candidate, str):
                        resolved = self._resolve_conversation_turn_budget_reference(
                            candidate,
                            user_model_config,
                            packaged_model_config,
                        )
                        if resolved is not None:
                            return resolved
                if model_alias != DEFAULT_MODEL and DEFAULT_MODEL in mapping:
                    candidate = mapping[DEFAULT_MODEL]
                    if isinstance(candidate, int):
                        return candidate
                    if isinstance(candidate, str):
                        resolved = self._resolve_conversation_turn_budget_reference(
                            candidate,
                            user_model_config,
                            packaged_model_config,
                        )
                        if resolved is not None:
                            return resolved

        return 0

    def _resolve_conversation_turn_budget_reference(
        self,
        reference: str,
        user_model_config: dict[str, object],
        packaged_model_config: dict[str, object],
    ) -> int | None:
        """Resolve a conversation turn budget reference through the selected alias."""

        alias = self._resolve_model_alias(reference, user_model_config, packaged_model_config)
        if alias == reference:
            alias = self._resolve_model_alias(DEFAULT_MODEL, user_model_config, packaged_model_config)

        if not alias:
            return None

        for model_config in (user_model_config, packaged_model_config):
            mapping = model_config.get("conversation_history_mapping")
            if isinstance(mapping, dict):
                value = mapping.get(alias)
                if isinstance(value, int):
                    return value
                if isinstance(value, str) and value != reference:
                    resolved = self._resolve_conversation_turn_budget_reference(
                        value,
                        user_model_config,
                        packaged_model_config,
                    )
                    if resolved is not None:
                        return resolved

        return None

    def _resolve_int_mapping_value(
        self,
        model_name: str,
        mapping_key: str,
        user_model_config: dict[str, object],
        packaged_model_config: dict[str, object],
        default: int,
    ) -> int:
        """Resolve an integer value from a top-level alias mapping."""

        candidate = self._resolve_mapping_value(
            model_name,
            mapping_key,
            user_model_config,
            packaged_model_config,
        )
        if candidate is None and model_name != DEFAULT_MODEL:
            candidate = self._resolve_mapping_value(
                DEFAULT_MODEL,
                mapping_key,
                user_model_config,
                packaged_model_config,
            )

        if candidate is None:
            return default

        if isinstance(candidate, dict):
            for value_key in ("default", "tier", "provider"):
                if value_key in candidate and candidate[value_key] is not None:
                    candidate = candidate[value_key]
                    break
            else:
                return default

        return self._coerce_int(candidate, default)

    def _resolve_mapping_value(
        self,
        model_name: str,
        mapping_key: str,
        user_model_config: dict[str, object],
        packaged_model_config: dict[str, object],
    ) -> object:
        """Resolve a raw value from user config first, then packaged config."""

        for model_config in (user_model_config, packaged_model_config):
            mapping = model_config.get(mapping_key)
            if isinstance(mapping, dict) and model_name in mapping:
                return mapping.get(model_name)

        return None

    def _resolve_mapping_string_value(
        self,
        model_name: str,
        mapping_key: str,
        user_model_config: dict[str, object],
        packaged_model_config: dict[str, object],
    ) -> str:
        """Resolve a string value from a top-level alias mapping."""

        value = self._resolve_mapping_value(
            model_name,
            mapping_key,
            user_model_config,
            packaged_model_config,
        )
        if value is None:
            return ""
        return str(value)

    def _normalize_model_config_section(
        self,
        model_config: dict[str, object],
        section_name: str,
    ) -> dict[str, object]:
        """Return a normalized mapping for flat sections or provider-tier tables."""

        section = model_config.get(section_name)
        if not isinstance(section, dict):
            return {}

        normalized: dict[str, object] = {}
        for key, value in section.items():
            if isinstance(value, dict):
                if "default" in value and value["default"] is not None:
                    normalized[str(key)] = value["default"]
                elif "tier" in value and value["tier"] is not None:
                    normalized[str(key)] = value["tier"]
                elif "provider" in value and value["provider"] is not None:
                    normalized[str(key)] = value["provider"]
            else:
                normalized[str(key)] = value

        return normalized

    def _resolve_normalized_model_config_value(
        self,
        model_name: str,
        section_name: str,
        user_model_config: dict[str, object],
        packaged_model_config: dict[str, object],
        default: object,
    ) -> object:
        """Resolve a value from normalized config sections with user precedence."""

        for model_config in (user_model_config, packaged_model_config):
            normalized = self._normalize_model_config_section(model_config, section_name)
            if model_name in normalized:
                return normalized[model_name]
            if model_name != DEFAULT_MODEL and DEFAULT_MODEL in normalized:
                return normalized[DEFAULT_MODEL]

        return default

    def _resolve_tokens_per_minute(
        self,
        model_alias: str,
        user_model_config: dict[str, object],
        packaged_model_config: dict[str, object],
    ) -> int:
        """Resolve tokens per minute using model_max_tpm and provider tables."""

        for model_config in (user_model_config, packaged_model_config):
            normalized_model_max_tpm = self._normalize_model_config_section(
                model_config,
                "model_max_tpm",
            )
            if model_alias in normalized_model_max_tpm:
                candidate = normalized_model_max_tpm[model_alias]
                if isinstance(candidate, str):
                    table_name, tier_key = self._parse_provider_table_reference(candidate)
                    if table_name and tier_key:
                        resolved = self._resolve_provider_table_value(
                            table_name,
                            tier_key,
                            user_model_config,
                            packaged_model_config,
                        )
                        if resolved is not None:
                            return self._coerce_int(resolved, 0)
                return self._coerce_int(candidate, 0)

            if model_alias != DEFAULT_MODEL and DEFAULT_MODEL in normalized_model_max_tpm:
                candidate = normalized_model_max_tpm[DEFAULT_MODEL]
                if isinstance(candidate, str):
                    table_name, tier_key = self._parse_provider_table_reference(candidate)
                    if table_name and tier_key:
                        resolved = self._resolve_provider_table_value(
                            table_name,
                            tier_key,
                            user_model_config,
                            packaged_model_config,
                        )
                        if resolved is not None:
                            return self._coerce_int(resolved, 0)
                return self._coerce_int(candidate, 0)

        return 0

    def _resolve_provider_table_value(
        self,
        table_name: str,
        tier_key: str,
        user_model_config: dict[str, object],
        packaged_model_config: dict[str, object],
    ) -> object | None:
        """Resolve a provider-tier value using user config before packaged config."""

        for model_config in (user_model_config, packaged_model_config):
            normalized_table = self._normalize_model_config_section(model_config, table_name)
            if tier_key in normalized_table:
                return normalized_table[tier_key]

        return None

    def _parse_provider_table_reference(self, reference: str) -> tuple[str, str]:
        """Parse a provider table reference in provider_table/tier_key form."""

        if "/" not in reference:
            return "", ""

        provider_table, tier_key = reference.split("/", 1)
        provider_table = provider_table.strip()
        tier_key = tier_key.strip()
        if not provider_table or not tier_key:
            return "", ""

        return provider_table, tier_key

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
