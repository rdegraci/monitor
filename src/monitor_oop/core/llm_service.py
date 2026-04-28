"""LLM service for the isolated Monitor OOP application."""
from __future__ import annotations

import logging
from typing import Any

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.llm_adapter import ResponsesLiteLLMAdapter
from monitor_oop.core.models import Message
from monitor_oop.core.tool_turn_state import ToolTurnState
from monitor_oop.core.tools.parsing import extract_tool_calls
from monitor_oop.core.tools.tool_service import ToolService

logger = logging.getLogger(__name__)


class LLMService:
    """Owns the Responses-via-LiteLLM adapter boundary for a single runtime instance."""

    _MAX_TOOL_LOOP_ROUNDS = 16

    def __init__(self, config_service: ConfigService, tool_service: ToolService | None = None) -> None:
        self.config_service = config_service
        self._tool_service = tool_service
        self.adapter = ResponsesLiteLLMAdapter()
        self._tool_turn_state = ToolTurnState()
        self._last_response_id: str | None = None

    def _build_request_input(self, user_input: str, history: list[str | Message]) -> list[dict[str, str]]:
        """Build request input from conversation history and the current user input."""

        input_messages: list[dict[str, str]] = []
        for item in history:
            if isinstance(item, Message):
                input_messages.append({"role": item.role, "content": item.content})
            elif isinstance(item, str):
                input_messages.append({"role": "user", "content": item})
        input_messages.append({"role": "user", "content": user_input})
        return input_messages

    def build_input(self, user_input: str, history: list[str | Message]) -> list[dict[str, str]]:
        """Build input for the Responses-via-LiteLLM adapter boundary call."""

        return self._build_request_input(user_input, history)

    def _strip_provider_prefix(self, model: str) -> str:
        """Strip the provider prefix from a configured model name."""

        if "/" in model:
            return model.split("/", 1)[1]
        return model

    def _build_litellm_tools(self) -> list[dict[str, Any]]:
        """Return the current flat Responses-style tool schemas for the adapter."""

        if self._tool_service is None:
            logger.info("Building LiteLLM tools: tool_service unavailable; tool count=0.")
            return []
        tools = self._tool_service.build_responses_tools()
        tool_names = [str(tool.get("name", "<unknown>")) for tool in tools]
        logger.info("Building LiteLLM tools: tool count=%s, tool names=%s.", len(tools), tool_names)
        return tools

    def _append_tool_output_to_input(
        self,
        input_messages: list[dict[str, str]],
        call_id: str,
        response_item_id: str,
        tool_result: Any,
        parent_response_id: str | None,
    ) -> list[dict[str, str]]:
        """Append tool output to request input for a follow-up model call."""

        if self._tool_service is None:
            logger.info("Skipping tool-output append: tool_service unavailable for tool_call_id=%s.", call_id)
            return input_messages
        logger.info(
            "Appending tool output to follow-up input for tool_call_id=%s with parent_response_id=%s.",
            call_id,
            parent_response_id,
        )
        return self._tool_service.build_follow_up_payload(
            input_messages,
            call_id,
            response_item_id,
            tool_result,
        )

    def _append_tool_outputs_to_input(
        self,
        input_messages: list[dict[str, str]],
        parent_response_id: str | None,
    ) -> list[dict[str, str]]:
        """Append multiple tool outputs to request input for a follow-up model call."""

        if self._tool_service is None:
            logger.info(
                "Skipping multi-tool follow-up append: tool_service unavailable; tool count=%s.",
                self._tool_turn_state.pending_count(),
            )
            return input_messages
        if self._tool_turn_state.pending_count() == 0:
            return input_messages
        logger.info(
            "Appending %s tool outputs to follow-up input with parent_response_id=%s; pending_count=%s.",
            self._tool_turn_state.pending_count(),
            parent_response_id,
            self._tool_turn_state.pending_count(),
        )
        follow_up_entries = self._tool_turn_state.build_follow_up_entries()
        return self._tool_service.build_follow_up_payloads(
            input_messages,
            follow_up_entries,
            parent_response_id,
        )

    def _record_tool_output_envelope(
        self,
        call_id: str,
        response_item_id: str | None,
        parent_response_id: str | None,
        tool_result: Any,
    ) -> None:
        """Store an internal envelope for tool output bookkeeping."""

        self._tool_turn_state.record_envelope(
            call_id,
            response_item_id,
            parent_response_id,
            tool_result,
        )
        logger.info(
            "Recorded tool output envelope for tool_call_id=%s, response_item_id=%s, parent_response_id=%s; pending_count=%s.",
            call_id,
            response_item_id,
            parent_response_id,
            self._tool_turn_state.pending_count(),
        )

    def _get_finish_reason(self, response: Any) -> str | None:
        """Return the finish_reason from a response."""

        finish_reason = getattr(response, "finish_reason", None)
        if finish_reason is None:
            return None
        return str(finish_reason)

    def _extract_tool_calls(self, response: Any) -> list[Any]:
        """Extract tool calls from response.output using the configured tool service parser."""

        response_output = getattr(response, "output", None)
        if self._tool_service is None:
            logger.info("Tool call parsing skipped: tool_service unavailable; response.output_type=%s.", type(response_output).__name__)
            return []
        tool_calls = extract_tool_calls(response_output)
        if tool_calls is None:
            logger.info("Tool call parsing on response.output produced no calls; response.output_type=%s.", type(response_output).__name__)
            return []
        tool_calls_list = list(tool_calls)
        logger.info("Parsed tool calls from response.output: count=%s.", len(tool_calls_list))
        return tool_calls_list

    def _execute_tool_calls(
        self,
        input_messages: list[dict[str, str]],
        response: Any,
    ) -> tuple[list[dict[str, str]], bool]:
        """Execute all parsed tool calls from a response when present."""

        tool_calls = self._extract_tool_calls(response)
        logger.info("Parsed tool calls from response: count=%s.", len(tool_calls))
        if not tool_calls:
            self._tool_turn_state.clear()
            return input_messages, False
        parent_response_id = getattr(response, "id", None)
        for tool_call in tool_calls:
            call_id = getattr(tool_call, "call_id", None)
            response_item_id = getattr(tool_call, "response_item_id", None)
            if response_item_id is None:
                response_item_id = getattr(tool_call, "id", None)
            logger.info(
                "Preparing to execute tool call with tool_call_id=%s, response_item_id=%s, response_id=%s.",
                call_id,
                response_item_id,
                parent_response_id,
            )
            tool_result = self._tool_service.execute_tool_call(tool_call)
            logger.info(
                "Executed tool call id=%s tool_name=%s; collecting follow-up input.",
                call_id,
                getattr(tool_call, "tool_name", None),
            )
            self._record_tool_output_envelope(
                call_id,
                response_item_id,
                parent_response_id,
                tool_result,
            )
        if self._tool_turn_state.pending_count() == 0:
            return input_messages, False
        follow_up_input = self._append_tool_outputs_to_input(
            input_messages,
            parent_response_id,
        )
        should_continue = True
        logger.info(
            "Tool follow-up decision: finish_reason=%s, should_continue=%s, follow_up_message_count=%s.",
            self._get_finish_reason(response),
            should_continue,
            len(follow_up_input),
        )
        return follow_up_input, should_continue

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
            self._tool_turn_state.clear()
            raise ValueError("Model response was filtered by the provider.")
        if finish_reason == "length":
            self._tool_turn_state.clear()
            raise ValueError("Model response stopped because it reached the length limit.")
        if self._tool_service is None:
            if finish_reason in ("stop", None):
                logger.info("No tool follow-up required for finish_reason=%s.", finish_reason)
            else:
                logger.info(
                    "Tool follow-up not attempted because tool_service is unavailable for finish_reason=%s.",
                    finish_reason,
                )
            self._tool_turn_state.clear()
            return input_messages, False
        tool_calls = self._extract_tool_calls(response)
        logger.info("Parsed tool calls from response: count=%s.", len(tool_calls))
        if tool_calls:
            return self._execute_tool_calls(input_messages, response)
        self._tool_turn_state.clear()
        if finish_reason in ("stop", None):
            logger.info("No tool follow-up required for finish_reason=%s.", finish_reason)
            return input_messages, False
        logger.info("No tool calls found; ending tool handling for finish_reason=%s.", finish_reason)
        return input_messages, False

    def _complete_with_tool_calls(self, input_messages: list[dict[str, str]]) -> Any:
        """Loop through tool calls until the model produces a final assistant response, with a defensive cap on total model calls."""

        self._tool_turn_state.begin_turn()
        request_input = input_messages
        total_model_calls = 1
        previous_response_id: str | None = self._last_response_id
        logger.info(
            "Starting response completion with initial message_count=%s, previous_response_id=%s.",
            len(request_input),
            previous_response_id,
        )
        try:
            response = self.create_response(request_input, previous_response_id=previous_response_id)
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
                response = self.create_response(request_input, previous_response_id=previous_response_id)
                self._last_response_id = getattr(response, "id", None)
                logger.info("Captured response.id=%s for current request.", self._last_response_id)
        finally:
            self._tool_turn_state.clear()

    def create_response(self, input_messages: list[dict[str, str]], previous_response_id: str | None = None) -> Any:
        """Create a response using the adapter completion API."""

        api_key = self.config_service.get_openai_api_key()
        if not api_key:
            raise ValueError("OpenAI API key is required to create a response.")
        model = self._strip_provider_prefix(self.config_service.get_model())
        tools = self._build_litellm_tools()
        tool_choice = "auto"
        tool_names = [str(tool.get("name", "<unknown>")) for tool in tools]
        logger.info(
            "Creating response with model=%s, tool_count=%s, tool_names=%s, tool_choice=%s, message_count=%s, previous_response_id=%s.",
            model,
            len(tools),
            tool_names,
            tool_choice,
            len(input_messages),
            previous_response_id,
        )
        return self.adapter.complete(
            model,
            input_messages,
            api_key=api_key,
            tools=tools,
            tool_choice=tool_choice,
            previous_response_id=previous_response_id,
        )

    def complete(self, user_input: str, history: list[str | Message]) -> str:
        """Call the configured model through the Responses-via-LiteLLM adapter boundary and return assistant text."""

        response = self._complete_with_tool_calls(self._build_request_input(user_input, history))
        return self.adapter.extract_text(response)
