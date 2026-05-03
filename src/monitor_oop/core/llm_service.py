"""LLM service for the isolated Monitor OOP application."""
from __future__ import annotations

import logging
from typing import Any

from monitor_oop.core.application.llm_request_builder import LLMRequestBuilder
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.infrastructure.llm_response_client import LLMResponseClient
from monitor_oop.core.llm_adapter import ResponsesLiteLLMAdapter
from monitor_oop.core.models import Message
from monitor_oop.core.tools.tool_call_handler import ToolCallHandler
from monitor_oop.core.tools.tool_service import ToolService

logger = logging.getLogger(__name__)


class LLMService:
    """Owns the Responses-via-LiteLLM adapter boundary for a single runtime instance."""

    _MAX_TOOL_LOOP_ROUNDS = 16

    def __init__(self, config_service: ConfigService, tool_service: ToolService | None = None) -> None:
        self.config_service = config_service
        self._tool_service = tool_service
        self._request_builder = LLMRequestBuilder()
        self.adapter = ResponsesLiteLLMAdapter()
        self._response_client = LLMResponseClient(config_service, tool_service)
        self._tool_call_handler = ToolCallHandler(tool_service)
        self._last_response_id: str | None = None

    def _build_litellm_tools(self) -> list[dict[str, Any]]:
        """Return the current flat Responses-style tool schemas for the adapter."""

        if self._tool_service is None:
            logger.info("Building LiteLLM tools: tool_service unavailable; tool count=0.")
            return []
        tools = self._tool_service.build_responses_tools()
        tool_names = [str(tool.get("name", "<unknown>")) for tool in tools]
        logger.info("Building LiteLLM tools: tool count=%s, tool names=%s.", len(tools), tool_names)
        return tools

    def _get_finish_reason(self, response: Any) -> str | None:
        """Return the finish_reason from a response."""

        finish_reason = getattr(response, "finish_reason", None)
        if finish_reason is None:
            return None
        return str(finish_reason)

    def _resolve_tool_call(self, input_messages: list[dict[str, str]], response: Any) -> tuple[list[dict[str, str]], bool]:
        """Resolve a tool call from a model response using the configured tool service."""

        finish_reason = self._get_finish_reason(response)
        response_output = getattr(response, "output", None)
        response_text = getattr(response, "text", None)
        response_message = getattr(response, "message", None)
        logger.info(
            "Response inspection before tool parsing: finish_reason=%s, output=%r, text=%r, message=%r.",
            finish_reason,
            response_output,
            response_text,
            response_message,
        )
        logger.info("Resolving response finish_reason=%s.", finish_reason)
        if finish_reason == "content_filter":
            raise ValueError("Model response was filtered by the provider.")
        if finish_reason == "length":
            raise ValueError("Model response stopped because it reached the length limit.")
        if self._tool_service is None:
            if finish_reason in ("stop", None):
                logger.info("No tool follow-up required for finish_reason=%s.", finish_reason)
            else:
                logger.info(
                    "Tool follow-up not attempted because tool_service is unavailable for finish_reason=%s.",
                    finish_reason,
                )
            return input_messages, False
        return self._tool_call_handler.execute_tool_calls(
            input_messages,
            response,
        )

    def _complete_with_tool_calls(self, input_messages: list[dict[str, str]]) -> Any:
        """Loop through tool calls until the model produces a final assistant response, with a defensive cap on total model calls."""

        request_input = input_messages
        total_model_calls = 1
        previous_response_id: str | None = self._last_response_id
        logger.info(
            "Starting response completion with initial message_count=%s, previous_response_id=%s.",
            len(request_input),
            previous_response_id,
        )
        response = self._response_client.create_response(
            request_input,
            previous_response_id=previous_response_id,
        )
        self._last_response_id = getattr(response, "id", None)
        logger.info("Captured response.id=%s for current request.", self._last_response_id)
        while True:
            request_input, should_continue = self._resolve_tool_call(request_input, response)
            logger.info("Tool-call handling result: should_continue=%s, message_count=%s.", should_continue, len(request_input))
            if not should_continue:
                return response
            total_model_calls += 1
            if total_model_calls > self._MAX_TOOL_LOOP_ROUNDS:
                raise RuntimeError("The maximum of 16 model calls was exceeded during tool-call completion.")
            previous_response_id = self._last_response_id
            logger.info(
                "Requesting follow-up response: total_model_calls=%s, previous_response_id=%s.",
                total_model_calls,
                previous_response_id,
            )
            response = self._response_client.create_response(
                request_input,
                previous_response_id=previous_response_id,
            )
            self._last_response_id = getattr(response, "id", None)
            logger.info("Captured response.id=%s for current request.", self._last_response_id)

    def complete(self, user_input: str, history: list[str | Message]) -> str:
        """Call the configured model through the Responses-via-LiteLLM adapter boundary and return assistant text."""

        response = self._complete_with_tool_calls(self._request_builder.build_input(user_input, history))
        return self.adapter.extract_text(response)
