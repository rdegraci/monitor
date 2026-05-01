"""Request-building helpers for Monitor OOP LLM flows."""
from __future__ import annotations

from monitor_oop.core.models import Message


class LLMRequestBuilder:
    """Build adapter-ready request inputs for LLM completions."""

    def build_input(self, user_input: str, history: list[str | Message]) -> list[dict[str, str]]:
        """Build request input from conversation history and the current user input.

        Args:
            user_input: The latest user message.
            history: Prior conversation items as strings or Message objects.

        Returns:
            A list of request messages suitable for adapter consumption.
        """

        input_messages: list[dict[str, str]] = []
        for item in history:
            if isinstance(item, Message):
                input_messages.append({"role": item.role, "content": item.content})
            elif isinstance(item, str):
                input_messages.append({"role": "user", "content": item})
        input_messages.append({"role": "user", "content": user_input})
        return input_messages

    def strip_provider_prefix(self, model: str) -> str:
        """Remove a provider prefix from a model name when present.

        Args:
            model: The configured model name.

        Returns:
            The model name without a leading `provider/` prefix.
        """

        if "/" in model:
            return model.split("/", 1)[1]
        return model
