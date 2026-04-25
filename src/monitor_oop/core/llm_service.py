"""LLM service for the isolated Monitor OOP application."""
from __future__ import annotations

from typing import Any

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.llm_adapter import ResponsesLiteLLMAdapter
from monitor_oop.core.models import Message
from monitor_oop.core.tools.tool_service import ToolService


class LLMService:
    """Owns the Responses-via-LiteLLM adapter boundary for a single runtime instance."""

    _MAX_TOOL_LOOP_ROUNDS = 5

    def __init__(self, config_service: ConfigService, tool_service: ToolService | None = None) -> None:
        self.config_service = config_service
        self._tool_service = tool_service
        self.adapter = ResponsesLiteLLMAdapter()

    def _build_request_messages(self, user_input: str, history: list[str | Message]) -> list[dict[str, str]]:
        """Build request messages from conversation history and the current user input."""

        messages: list[dict[str, str]] = []
        for item in history:
            if isinstance(item, Message):
                messages.append({"role": item.role, "content": item.content})
            elif isinstance(item, str):
                messages.append({"role": "user", "content": item})
        messages.append({"role": "user", "content": user_input})
        return messages

    def build_messages(self, user_input: str, history: list[str | Message]) -> list[dict[str, str]]:
        """Build chat messages for the Responses-via-LiteLLM adapter boundary call."""

        return self._build_request_messages(user_input, history)

    def _strip_provider_prefix(self, model: str) -> str:
        """Strip the provider prefix from a configured model name."""

        if "/" in model:
            return model.split("/", 1)[1]
        return model

    def _build_litellm_tools(self) -> list[dict[str, Any]]:
        """Return the current LiteLLM tool schemas for the adapter."""

        if self._tool_service is None:
            return []
        return self._tool_service.build_litellm_tools()

    def _append_tool_output_to_messages(
        self,
        messages: list[dict[str, str]],
        tool_call_id: str,
        tool_result: Any,
    ) -> list[dict[str, str]]:
        """Append tool output to request messages for a follow-up model call."""

        if self._tool_service is None:
            return messages
        return self._tool_service.build_follow_up_payload(messages, tool_call_id, tool_result)

    def _get_finish_reason(self, response: Any) -> str | None:
        """Return the finish_reason from a response."""

        finish_reason = getattr(response, "finish_reason", None)
        if finish_reason is None:
            return None
        return str(finish_reason)

    def _resolve_tool_call(self, messages: list[dict[str, str]], response: Any) -> tuple[list[dict[str, str]], bool]:
        """Resolve a tool call from a model response using the configured tool service."""

        finish_reason = self._get_finish_reason(response)
        if finish_reason == "content_filter":
            raise ValueError("Model response was filtered by the provider.")
        if finish_reason == "length":
            raise ValueError("Model response stopped because it reached the length limit.")
        if finish_reason in ("stop", None):
            return messages, False
        if self._tool_service is None:
            return messages, False
        tool_call = self._tool_service.parse_tool_call(response)
        if tool_call is None:
            if finish_reason == "tool_calls":
                raise ValueError("Model response indicated tool calls, but the tool call response was malformed.")
            return messages, False
        tool_result = self._tool_service.execute_tool_call(tool_call)
        follow_up_messages = self._append_tool_output_to_messages(messages, tool_call.call_id, tool_result)
        return follow_up_messages, finish_reason == "tool_calls"

    def _complete_with_tool_calls(self, messages: list[dict[str, str]]) -> Any:
        """Loop through tool calls until the model produces a final assistant response, with a defensive cap on total model calls."""

        request_messages = messages
        total_model_calls = 1
        response = self.create_response(request_messages)
        while True:
            request_messages, should_continue = self._resolve_tool_call(request_messages, response)
            if not should_continue:
                return response
            total_model_calls += 1
            if total_model_calls > self._MAX_TOOL_LOOP_ROUNDS:
                raise RuntimeError("The maximum of 5 model calls was exceeded during tool-call completion.")
            response = self.create_response(request_messages)

    def create_response(self, messages: list[dict[str, str]]) -> Any:
        """Create a response using the adapter completion API."""

        api_key = self.config_service.get_openai_api_key()
        if not api_key:
            raise ValueError("OpenAI API key is required to create a response.")
        model = self._strip_provider_prefix(self.config_service.get_model())
        return self.adapter.complete(
            model,
            messages,
            api_key=api_key,
            tools=self._build_litellm_tools(),
            tool_choice="auto",
        )

    def complete(self, user_input: str, history: list[str | Message]) -> str:
        """Call the configured model through the Responses-via-LiteLLM adapter boundary and return assistant text."""

        response = self._complete_with_tool_calls(self._build_request_messages(user_input, history))
        return self.adapter.extract_text(response)
