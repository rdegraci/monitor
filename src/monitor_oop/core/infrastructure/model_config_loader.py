"""Model configuration loading for Monitor OOP."""
from __future__ import annotations

import appdirs
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from monitor_oop.core.config_path_service import ConfigPathService

logger = logging.getLogger(__name__)


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


class ModelConfigLoader:
    """Load and resolve model configuration from JSON sources."""

    def __init__(self) -> None:
        """Initialize model configuration attributes.

        Attributes:
            model_alias: The resolved model alias.
            provider: The model provider.
            full_model_name: The full provider/model name.
            context_window: The model context window.
            output_window: The model output window.
            conversation_turn_budget: The conversation turn budget.
            tokens_per_minute: The tokens-per-minute rate limit.
            requests_per_minute: The requests-per-minute rate limit.
        """
        self.model_alias = ""
        self.provider = ""
        self.full_model_name = ""
        self.context_window = 0
        self.output_window = 0
        self.conversation_turn_budget = 0
        self.tokens_per_minute = 0
        self.requests_per_minute = 0

    def get_packaged_config_path(self) -> Path:
        """Return the packaged configuration file path.

        Returns:
            The packaged configuration file path shipped with the application.
        """
        return Path(__file__).resolve().parents[2] / "model_config_v2.json"

    def get_user_config_dir_path(self) -> Path:
        """Return the user configuration directory path.

        Returns:
            The user configuration directory path provided by appdirs.
        """
        return Path(appdirs.user_config_dir("monitor_oop"))

    def get_user_config_path(self) -> Path:
        """Return the user configuration file path.

        Returns:
            The user configuration file path in the user config directory.
        """
        return self.get_user_config_dir_path() / "model_config_v2.json"

    def get_model_config_path(self) -> Path:
        """Return the preferred model configuration file path.

        Returns:
            The user configuration file path when present, otherwise the
            packaged configuration file path.
        """
        user_config_path = self.get_user_config_path()
        if user_config_path.exists():
            logger.info("Loading model configuration from user config path %s", user_config_path)
            return user_config_path

        packaged_config_path = self.get_packaged_config_path()
        logger.info(
            "Loading model configuration from packaged config path %s",
            packaged_config_path,
        )
        return packaged_config_path

    def resolve_provider_value(self, model_name: str) -> str:
        """Return the provider name from a provider/model string.

        Args:
            model_name: The provider/model string to resolve.

        Returns:
            The substring before the first "/" character.

        Raises:
            ValueError: If `model_name` does not contain a "/" character.
        """
        if "/" not in model_name:
            raise ValueError(
                f"model_name must contain '/' to resolve a provider value: {model_name!r}"
            )
        return model_name.split("/", 1)[0]

    def resolve_model_mapping_value(self, model_name: str) -> str:
        """Return the canonical model mapping value from a provider/model string.

        Args:
            model_name: The provider/model string to resolve.

        Returns:
            The substring after the first "/" character.

        Raises:
            ValueError: If `model_name` does not contain a "/" character.
        """
        if "/" not in model_name:
            raise ValueError(
                f"model_name must contain '/' to resolve a model mapping value: {model_name!r}"
            )
        return model_name.split("/", 1)[1]

    def _load_model_config_data(self) -> dict[str, object]:
        """Load and validate the packaged JSON configuration data."""
        config_path = self.get_model_config_path()
        try:
            with config_path.open("r", encoding="utf-8") as config_file:
                config_data = json.load(config_file)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Failed to read or parse model configuration file {config_path}: {exc}"
            ) from exc

        if not isinstance(config_data, dict):
            raise ValueError(f"model configuration must be a dictionary in {config_path}")

        return config_data

    def _load_model_mapping(self) -> dict[str, str]:
        """Load the model mapping table from the packaged configuration."""
        config_data = self._load_model_config_data()
        config_path = self.get_model_config_path()

        try:
            model_mapping = config_data["model_mapping"]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"model_mapping is missing or invalid in {config_path}"
            ) from exc

        if not isinstance(model_mapping, dict):
            raise ValueError(f"model_mapping must be a dictionary in {config_path}")

        return model_mapping

    def resolve_model_alias_value(
        self, model_name: str, config_data: dict[str, object] | None = None
    ) -> str:
        """Return the canonical model alias for a provider/model string.

        Args:
            model_name: The provider/model string to resolve.

        Returns:
            The canonical model alias from the packaged model_mapping table, or
            the provided model_name if no mapping exists.

        Raises:
            ValueError: If the configuration file cannot be read or parsed.
        """
        if config_data is None:
            config_data = self._load_model_config_data()

        config_path = self.get_model_config_path()

        try:
            model_mapping = config_data["model_mapping"]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"model_mapping is missing or invalid in {config_path}"
            ) from exc

        if not isinstance(model_mapping, dict):
            raise ValueError(f"model_mapping must be a dictionary in {config_path}")

        mapped_value = model_mapping.get(model_name)
        if mapped_value is not None:
            logger.info(
                "Resolved model alias using exact full model name key %r -> %r",
                model_name,
                mapped_value,
            )
            return mapped_value

        if "/" in model_name:
            suffix = model_name.split("/", 1)[1]
            mapped_value = model_mapping.get(suffix)
            if mapped_value is not None:
                logger.info(
                    "Resolved model alias using exact suffix key %r -> %r",
                    suffix,
                    mapped_value,
                )
                return mapped_value

        logger.info(
            "No exact model alias mapping found for %r; returning original model name",
            model_name,
        )
        return model_name

    def resolve_conversation_history_mapping_value(
        self, model_alias: str, config_data: dict[str, object] | None = None
    ) -> int:
        """Return the conversation history budget for a model alias.

        Args:
            model_alias: The canonical model alias to resolve.

        Returns:
            The conversation turn budget for the given model alias.

        Raises:
            ValueError: If the configuration file cannot be read or parsed, or if
                the model alias is missing from the conversation history mapping.
        """
        if config_data is None:
            config_data = self._load_model_config_data()

        config_path = self.get_model_config_path()

        try:
            conversation_history_mapping = config_data["conversation_history_mapping"]
            value = conversation_history_mapping[model_alias]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"Model alias {model_alias!r} is missing from conversation_history_mapping in {config_path}"
            ) from exc

        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Conversation history mapping value for {model_alias!r} must be an integer in {config_path}: {value!r}"
            ) from exc

    def resolve_context_window_mapping_value(
        self, model_alias: str, config_data: dict[str, object] | None = None
    ) -> int:
        """Return the context window for a model alias.

        Args:
            model_alias: The canonical model alias to resolve.

        Returns:
            The context window for the given model alias.

        Raises:
            ValueError: If the configuration file cannot be read or parsed, or if
                the model alias is missing from the context window mapping.
        """
        if config_data is None:
            config_data = self._load_model_config_data()

        config_path = self.get_model_config_path()

        try:
            context_window_mapping = config_data["context_window_mapping"]
            value = context_window_mapping[model_alias]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"Model alias {model_alias!r} is missing from context_window_mapping in {config_path}"
            ) from exc

        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Context window mapping value for {model_alias!r} must be an integer in {config_path}: {value!r}"
            ) from exc

    def resolve_output_window_mapping_value(
        self, model_alias: str, config_data: dict[str, object] | None = None
    ) -> int:
        """Return the output window for a model alias.

        Args:
            model_alias: The canonical model alias to resolve.

        Returns:
            The output window for the given model alias.

        Raises:
            ValueError: If the configuration file cannot be read or parsed, or if
                the model alias is missing from the output window mapping.
        """
        if config_data is None:
            config_data = self._load_model_config_data()

        config_path = self.get_model_config_path()

        try:
            output_window_mapping = config_data["output_window_mapping"]
            value = output_window_mapping[model_alias]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"Model alias {model_alias!r} is missing from output_window_mapping in {config_path}"
            ) from exc

        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Output window mapping value for {model_alias!r} must be an integer in {config_path}: {value!r}"
            ) from exc

    def resolve_requests_per_minute_mapping_value(
        self, model_alias: str, config_data: dict[str, object] | None = None
    ) -> int:
        """Return the requests-per-minute limit for a model alias.

        Args:
            model_alias: The canonical model alias to resolve.

        Returns:
            The requests-per-minute limit for the given model alias.

        Raises:
            ValueError: If the configuration file cannot be read or parsed, if the
                model alias is missing from model_max_rpm, if the tier table is
                missing or invalid, or if the tier value is not an integer.
        """
        if config_data is None:
            config_data = self._load_model_config_data()

        config_path = self.get_model_config_path()

        try:
            model_max_rpm = config_data["model_max_rpm"]
            tier_reference = model_max_rpm[model_alias]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"Model alias {model_alias!r} is missing from model_max_rpm in {config_path}"
            ) from exc

        if "/" not in tier_reference:
            raise ValueError(
                f"Tier reference {tier_reference!r} is invalid in {config_path}"
            )

        tier_table_name, tier_key = tier_reference.split("/", 1)

        try:
            return int(config_data[tier_table_name][tier_key])
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"Tier reference {tier_reference!r} is missing from {config_path}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Requests-per-minute mapping value for {model_alias!r} must be an integer in {config_path}: {config_data[tier_table_name][tier_key]!r}"
            ) from exc

    def resolve_tokens_per_minute_mapping_value(
        self, model_alias: str, config_data: dict[str, object] | None = None
    ) -> int:
        """Return the tokens-per-minute limit for a model alias.

        Args:
            model_alias: The canonical model alias to resolve.

        Returns:
            The tokens-per-minute limit for the given model alias.

        Raises:
            ValueError: If the configuration file cannot be read or parsed, if the
                model alias is missing from model_max_tpm, if the tier table is
                missing or invalid, or if the tier value is not an integer.
        """
        if config_data is None:
            config_data = self._load_model_config_data()

        config_path = self.get_model_config_path()

        try:
            model_max_tpm = config_data["model_max_tpm"]
            tier_reference = model_max_tpm[model_alias]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"Model alias {model_alias!r} is missing from model_max_tpm in {config_path}"
            ) from exc

        if "/" not in tier_reference:
            raise ValueError(
                f"Tier reference {tier_reference!r} is invalid in {config_path}"
            )

        tier_table_name, tier_key = tier_reference.split("/", 1)

        try:
            return int(config_data[tier_table_name][tier_key])
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"Tier reference {tier_reference!r} is missing from {config_path}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Tokens-per-minute mapping value for {model_alias!r} must be an integer in {config_path}: {config_data[tier_table_name][tier_key]!r}"
            ) from exc

    def load_model_config(self, model_name: str) -> LoadedModelConfig:
        """Load and store the canonical model alias for a provider/model string.

        Args:
            model_name: The provider/model string to resolve.

        Returns:
            The resolved canonical model alias.
        """
        config_data = self._load_model_config_data()
        self.provider = self.resolve_provider_value(model_name)
        self.full_model_name = model_name
        model_alias = self.resolve_model_alias_value(model_name, config_data=config_data)
        self.model_alias = model_alias
        self.conversation_turn_budget = self.resolve_conversation_history_mapping_value(
            model_alias, config_data=config_data
        )
        self.context_window = self.resolve_context_window_mapping_value(
            model_alias, config_data=config_data
        )
        self.output_window = self.resolve_output_window_mapping_value(
            model_alias, config_data=config_data
        )
        self.requests_per_minute = self.resolve_requests_per_minute_mapping_value(
            model_alias, config_data=config_data
        )
        self.tokens_per_minute = self.resolve_tokens_per_minute_mapping_value(
            model_alias, config_data=config_data
        )
        return LoadedModelConfig(
            model_alias=self.model_alias,
            provider=self.provider,
            full_model_name=self.full_model_name,
            context_window=self.context_window,
            output_window=self.output_window,
            conversation_turn_budget=self.conversation_turn_budget,
            tokens_per_minute=self.tokens_per_minute,
            requests_per_minute=self.requests_per_minute,
        )
