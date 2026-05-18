"""Runtime configuration accessors for Monitor OOP."""
from __future__ import annotations

from typing import Any

from monitor_oop.core.models import RuntimeConfig


class ConfigAccessorService:
    """Expose read-only runtime configuration accessors."""

    def __init__(
        self,
        config: RuntimeConfig,
        openai_api_key: str | None,
        logging_level: int,
    ) -> None:
        """Initialize the accessor service.

        Args:
            config: Runtime configuration to read from.
            openai_api_key: Effective OPENAI_API_KEY for this runtime.
            logging_level: Effective logging level for this runtime.
        """

        self._config = config
        self._openai_api_key = openai_api_key
        self._logging_level = logging_level

    def get_model(self) -> str:
        """Return the active model name."""

        return self._config.api_model_name

    def get_model_alias(self) -> str | None:
        """Return the compatibility model alias, if configured."""

        return getattr(self._config, "model_alias", None)

    def get_full_model_name(self) -> str | None:
        """Return the compatibility full model name, if configured."""

        return getattr(self._config, "full_model_name", None)

    def _resolve_provider(self) -> str:
        """Return the provider prefix for the active model name."""

        full_model_name = self.get_full_model_name()
        if full_model_name and "/" in full_model_name:
            return full_model_name.split("/", 1)[0]

        provider = getattr(self._config, "provider", None)
        if provider:
            return provider

        return "openai"

    def get_provider(self) -> str:
        """Return the provider prefix for the active model name."""

        return self._resolve_provider()

    def estimate_token_usage(
        self,
        model: str,
        messages: list[dict[str, Any]] | None,
        tools: list[dict[str, Any]] | None,
        previous_response_id: str | None,
    ) -> int:
        """Estimate token usage for a request.

        Args:
            model: The model name being used for the request.
            messages: The request messages.
            tools: The request tools.
            previous_response_id: The previous response identifier, if any.

        Returns:
            A conservative estimate of token usage for the request.
        """

        del model
        estimated_tokens = 0
        if messages:
            for message in messages:
                for value in message.values():
                    if isinstance(value, str):
                        estimated_tokens += max(1, len(value) // 4)
                    elif isinstance(value, list):
                        estimated_tokens += len(value) * 4
                    elif isinstance(value, dict):
                        estimated_tokens += len(value) * 2
                    elif value is not None:
                        estimated_tokens += 1
        if tools:
            estimated_tokens += len(tools) * 20
        if previous_response_id:
            estimated_tokens += max(1, len(previous_response_id) // 4)
        return max(1, estimated_tokens)

    def get_context_window(self) -> int:
        """Return the active context window size."""

        return self._config.context_window

    def get_output_window(self) -> int:
        """Return the active output window size."""

        return self._config.output_window

    def get_summarization_prompt_template(self) -> str:
        """Return the summarization prompt template for the active runtime."""

        return self._config.summarization_settings.prompt_template

    def get_summarization_token_limit(self) -> int:
        """Return the summarization token limit for the active runtime."""

        return self._config.summarization_settings.token_limit

    def get_compaction_preserve_units(self) -> int:
        """Return the number of conversational units to preserve during compaction."""

        return self._config.summarization_settings.preserve_units

    def get_compaction_soft_ratio(self) -> float:
        """Return the soft-trigger ratio of context window for proactive compaction."""

        return self._config.summarization_settings.compaction_soft_ratio

    def get_conversation_turn_budget(self) -> int:
        """Return the conversation turn budget for the active runtime."""

        return self._config.conversation_turn_budget

    def _resolve_model_name(self, model_name: str | None) -> str:
        """Return the requested model name or the current runtime model."""

        if model_name:
            return model_name
        full_model_name = self.get_full_model_name()
        if full_model_name:
            return full_model_name
        return self._config.api_model_name

    def _get_rate_limit_fallback(self, model_name: str, limit_name: str) -> int | None:
        """Return a model-specific rate limit fallback value, if configured."""

        return getattr(self._config, f"{model_name}_{limit_name}", None)

    def _get_model_rate_limit(
        self,
        model_name: str | None,
        config_primary_name: str,
        config_alias_name: str,
        model_primary_name: str,
        model_alias_name: str,
        default: int,
    ) -> int:
        """Return a model rate limit using config and model-specific fallbacks."""

        resolved_model_name = self._resolve_model_name(model_name)
        limit = getattr(self._config, config_primary_name, None)
        if limit is None:
            limit = getattr(self._config, config_alias_name, None)
        if limit is None and resolved_model_name != self._config.api_model_name:
            limit = self._get_rate_limit_fallback(resolved_model_name, model_primary_name)
            if limit is None:
                limit = self._get_rate_limit_fallback(resolved_model_name, model_alias_name)
        if limit is None:
            return default
        return limit

    def get_model_tpm_limit(self, model_name: str | None = None) -> int:
        """Return the tokens-per-minute limit for a model."""

        return self._get_model_rate_limit(
            model_name,
            "tokens_per_minute",
            "tpm_limit",
            "tokens_per_minute",
            "tpm_limit",
            1,
        )

    def get_model_rpm_limit(self, model_name: str | None = None) -> int:
        """Return the requests-per-minute limit for a model."""

        return self._get_model_rate_limit(
            model_name,
            "requests_per_minute",
            "rpm_limit",
            "requests_per_minute",
            "rpm_limit",
            0,
        )

    def get_openai_api_key(self) -> str | None:
        """Return the effective OPENAI_API_KEY for this runtime."""

        return self._openai_api_key

    def get_logging_level(self) -> int:
        """Return the logging level for this runtime."""

        return self._logging_level
