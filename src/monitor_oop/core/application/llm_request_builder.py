"""Request-building helpers for Monitor OOP LLM flows."""
from __future__ import annotations

import logging

from monitor_oop.core.models import Message

logger = logging.getLogger(__name__)


class LLMRequestBuilder:
    """Build adapter-ready request inputs for LLM completions."""

    def __init__(
        self,
        prompt_text: str | None = None,
    ) -> None:
        """Initialize a request builder.

        Args:
            prompt_text: Optional injected system prompt text.
        """

        self._prompt_text = prompt_text

    def build_input(
        self,
        user_input: str,
        history: list[str | Message],
        prompt_text: str | None = None,
    ) -> list[dict[str, str]]:
        """Build request input from conversation history and the current user input.

        Args:
            user_input: The latest user message.
            history: Prior conversation items as strings or Message objects.
            prompt_text: Optional injected system prompt text.

        Returns:
            A list of request messages suitable for adapter consumption.
        """

        input_messages: list[dict[str, str]] = []
        resolved_prompt_text = self._resolve_prompt_text(prompt_text)
        if resolved_prompt_text is not None:
            input_messages.append({"role": "system", "content": resolved_prompt_text})
        input_messages.extend(self._history_items_to_request_messages(history))
        input_messages.append({"role": "user", "content": user_input})
        return input_messages

    def build_summarization_input(
        self,
        prompt_text: str,
        message_history: list[Message],
        token_limit: int | None = None,
    ) -> list[dict[str, str]]:
        """Build request input for summary generation.

        Args:
            prompt_text: The summary prompt text.
            message_history: Prior conversation messages to summarize.
            token_limit: Optional token limit directive to include in the system prompt.

        Returns:
            A list of request messages suitable for adapter consumption.
        """

        input_messages: list[dict[str, str]] = self._build_summarization_preamble_messages(
            prompt_text,
            token_limit,
        )
        for item in message_history:
            input_messages.append({"role": item.role, "content": item.content})
        return input_messages

    def strip_provider_prefix(self, model: str) -> str:
        """Remove a provider prefix from a model name when present.

        Args:
            model: The configured model name.

        Returns:
            The model name without a leading `provider/` prefix.
        """

        return self._strip_provider_prefix(model)

    def _resolve_prompt_text(self, prompt_text: str | None = None) -> str | None:
        if prompt_text is not None:
            return prompt_text
        return self._prompt_text

    def _history_items_to_request_messages(
        self,
        history: list[str | Message],
    ) -> list[dict[str, str]]:
        request_messages: list[dict[str, str]] = []
        for item in history:
            if isinstance(item, Message):
                request_messages.append({"role": item.role, "content": item.content})
            elif isinstance(item, str):
                request_messages.append({"role": "user", "content": item})
        return request_messages

    def _build_summarization_preamble_messages(
        self,
        prompt_text: str,
        token_limit: int | None = None,
    ) -> list[dict[str, str]]:
        preamble_messages: list[dict[str, str]] = [{"role": "system", "content": prompt_text}]
        if token_limit is not None:
            preamble_messages.append(
                {
                    "role": "system",
                    "content": f"Token limit: {token_limit}",
                }
            )
        return preamble_messages

    def _strip_provider_prefix(self, model: str) -> str:
        if "/" in model:
            return model.split("/", 1)[1]
        return model
