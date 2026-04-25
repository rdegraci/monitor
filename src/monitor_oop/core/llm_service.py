"""LLM service for the isolated Monitor OOP application."""
from __future__ import annotations

from typing import Any

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.llm_adapter import ResponsesLiteLLMAdapter
from monitor_oop.core.models import Message


class LLMService:
    """Owns the Responses-via-LiteLLM adapter boundary for a single runtime instance."""

    def __init__(self, config_service: ConfigService) -> None:
        self.config_service = config_service
        self.adapter = ResponsesLiteLLMAdapter()

    def build_messages(self, user_input: str, history: list[str | Message]) -> list[dict[str, str]]:
        """Build chat messages for the Responses-via-LiteLLM adapter boundary call."""

        messages: list[dict[str, str]] = []
        for item in history:
            if isinstance(item, Message):
                messages.append({"role": item.role, "content": item.content})
            elif isinstance(item, str):
                messages.append({"role": "user", "content": item})
        messages.append({"role": "user", "content": user_input})
        return messages

    def _strip_provider_prefix(self, model: str) -> str:
        """Strip the provider prefix from a configured model name."""

        if "/" in model:
            return model.split("/", 1)[1]
        return model

    def create_response(self, messages: list[dict[str, str]]) -> Any:
        """Create a response using the adapter completion API."""

        api_key = self.config_service.get_openai_api_key()
        if not api_key:
            raise ValueError("OpenAI API key is required to create a response.")
        model = self._strip_provider_prefix(self.config_service.get_model())
        return self.adapter.complete(model, messages, api_key=api_key)

    def complete(self, user_input: str, history: list[str | Message]) -> str:
        """Call the configured model through the Responses-via-LiteLLM adapter boundary and return assistant text."""

        response = self.create_response(self.build_messages(user_input, history))
        return self.adapter.extract_text(response)
