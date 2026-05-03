"""Tool-call handling helpers for Monitor OOP LLM flows."""
from __future__ import annotations

import logging
from typing import Any

from monitor_oop.core.tool_turn_state import ToolTurnState
from monitor_oop.core.tools.parsing import extract_tool_calls
from monitor_oop.core.tools.tool_service import ToolService

logger = logging.getLogger(__name__)


class ToolCallHandler:
    """Parse and execute tool calls for a single model turn."""

    def __init__(
        self,
        tool_service: ToolService | None = None,
    ) -> None:
        """Initialize the handler.

        Args:
            tool_service: Optional tool execution service.
            tool_turn_state: Optional per-turn state override for testing.
        """

        self._tool_service = tool_service
        self._tool_turn_state = ToolTurnState()

    def _append_tool_output_to_input(
        self,
        input_messages: list[dict[str, str]],
        call_id: str,
        response_item_id: str,
        tool_result: Any,
        parent_response_id: str | None,
    ) -> list[dict[str, str]]:
        """Append one tool output to follow-up input when available."""

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
        """Append multiple tool outputs to follow-up input when available."""

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

    def _extract_tool_calls(self, response: Any) -> list[Any]:
        """Extract tool calls from a model response."""

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

    def execute_tool_calls(
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
            "Tool follow-up decision: should_continue=%s, follow_up_message_count=%s.",
            should_continue,
            len(follow_up_input),
        )
        return follow_up_input, should_continue
