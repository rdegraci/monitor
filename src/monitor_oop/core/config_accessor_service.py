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

        This is the canonical token estimator for the runtime. Both the
        rate-limit preflight and the request-capacity preflight delegate
        here so they evaluate identical numbers. The formula:

        - Per message: 4 tokens of fixed overhead (role separators / framing),
          plus a per-field contribution based on the field's value type
          (strings: ``len(value) // 4``; lists: ``len * 4``; dicts: ``len * 2``;
          other non-None scalars: ``1``).
        - Per tool: ``20`` tokens (rough schema/header overhead).
        - Previous response id: ``len // 4`` tokens for the id string itself
          (the chained server-side context is added separately by callers
          that have a token cache).

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
                # Fixed per-message overhead (role separator / framing).
                estimated_tokens += 4
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

    def get_model_tpm_limit(self, model_name: str | None = None) -> int | None:
        """Return the tokens-per-minute limit for a model.

        Returns ``None`` when ``tokens_per_minute`` is unset *or* explicitly
        ``0`` — both forms mean "disabled" and are treated identically by the
        rate-limit service. Per-model overrides are not supported; the
        ``model_name`` argument is accepted for API symmetry but ignored.
        """

        del model_name
        value = self._config.tokens_per_minute
        return None if value == 0 else value

    def get_model_rpm_limit(self, model_name: str | None = None) -> int | None:
        """Return the requests-per-minute limit for a model.

        Returns ``None`` when ``requests_per_minute`` is unset *or* explicitly
        ``0`` — both forms mean "disabled" and are treated identically by the
        rate-limit service. Per-model overrides are not supported; the
        ``model_name`` argument is accepted for API symmetry but ignored.
        """

        del model_name
        value = self._config.requests_per_minute
        return None if value == 0 else value

    def get_openai_api_key(self) -> str | None:
        """Return the effective OPENAI_API_KEY for this runtime."""

        return self._openai_api_key

    def get_logging_level(self) -> int:
        """Return the logging level for this runtime."""

        return self._logging_level
