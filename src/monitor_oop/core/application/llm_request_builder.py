"""Request-building helpers for Monitor OOP LLM flows."""
from __future__ import annotations

from monitor_oop.core.models import Message


class LLMRequestBuilder:
    """Build adapter-ready request inputs for LLM completions."""

    def __init__(self, prompt_service: object | None = None, prompt_text: str | None = None) -> None:
        """Initialize a request builder.

        Args:
            prompt_service: Optional service used to resolve the system prompt.
            prompt_text: Optional resolved system prompt text.
        """

        self._prompt_service = prompt_service
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
            prompt_text: Optional resolved system prompt text.

        Returns:
            A list of request messages suitable for adapter consumption.
        """

        input_messages: list[dict[str, str]] = []
        resolved_prompt_text = prompt_text if prompt_text is not None else self._prompt_text
        if resolved_prompt_text is None and self._prompt_service is not None:
            get_resolved_prompt_text = getattr(self._prompt_service, "get_resolved_prompt_text", None)
            if callable(get_resolved_prompt_text):
                resolved_prompt_text = get_resolved_prompt_text()
            else:
                get_prompt = getattr(self._prompt_service, "get_prompt", None)
                if callable(get_prompt):
                    resolved_prompt_text = get_prompt()
        if resolved_prompt_text is not None:
            input_messages.append({"role": "system", "content": resolved_prompt_text})
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
