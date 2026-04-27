"""Tool execution service for Monitor OOP."""
from __future__ import annotations

import logging
from collections.abc import Callable

from monitor_oop.core.tools.parsing import build_tool_call_output, parse_tool_call as _parse_tool_call, parse_tool_calls as _parse_tool_calls
from monitor_oop.core.tools.registry import ToolRegistry
from monitor_oop.core.tools.tool_models import ToolCall, ToolDefinition, ToolResult

logger = logging.getLogger(__name__)


class ToolService:
    """Execute tools through a registry-backed boundary."""

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._tool_registry = tool_registry

    def execute(self, tool_name: str, arguments: dict[str, object]) -> ToolResult:
        """Execute a registered tool."""

        logger.info("Executing tool: %s", tool_name)
        tool = self._tool_registry.resolve(tool_name)
        if tool is None:
            logger.info("Tool not found during execution: %s", tool_name)
            return ToolResult(tool_name=tool_name, success=False, output="", error=f"Tool not found: {tool_name}")
        handler = self._tool_registry.get_handler(tool_name)
        if handler is None:
            logger.info("Tool handler not found during execution: %s", tool_name)
            return ToolResult(tool_name=tool_name, success=False, output="", error=f"Tool handler not found: {tool_name}")
        validated_arguments = self._validate_arguments(tool, arguments)
        if validated_arguments is None:
            logger.info("Invalid tool arguments for execution: %s", tool_name)
            return ToolResult(tool_name=tool_name, success=False, output="", error="Invalid tool arguments.")
        try:
            output = handler(**validated_arguments)
            logger.info("Tool execution completed: %s", tool_name)
            return ToolResult(tool_name=tool_name, success=True, output=str(output))
        except Exception as exc:
            logger.info("Tool execution failed: %s", tool_name)
            return ToolResult(tool_name=tool_name, success=False, output="", error=str(exc))

    def execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
        """Resolve and execute a tool call."""

        return self.execute(tool_call.tool_name, tool_call.arguments)

    def parse_tool_call(self, value: object) -> ToolCall | None:
        """Parse a tool call using the shared free parsing helper."""

        return _parse_tool_call(value)

    def parse_tool_calls(self, value: object) -> list[ToolCall]:
        """Parse all tool calls from a response-like value."""

        return _parse_tool_calls(value)

    def build_follow_up_payload(
        self,
        messages: list[dict[str, object]] | None,
        call_id: str,
        response_item_id: str | None = None,
        result: ToolResult | None = None,
        parent_response_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Build a follow-up payload using the shared parsing helper."""

        logger.info("Building follow-up payload for tool call: %s", call_id)
        logger.info("Follow-up payload response item id is metadata only: %s", response_item_id)
        payload = list(messages) if messages is not None else []
        payload_item = build_tool_call_output(
            call_id,
            result if result is not None else ToolResult(tool_name=call_id, success=False, output="", error="Missing tool result."),
        )
        logger.info("Follow-up payload item: %s", payload_item)
        logger.info("Follow-up payload built without a duplicate payload id for tool call: %s", call_id)
        payload.append(payload_item)
        logger.info("Follow-up payload built for tool call: %s", call_id)
        return payload

    def build_follow_up_payloads(
        self,
        messages: list[dict[str, object]] | None,
        envelopes: list[ToolCall | ToolResult | tuple[ToolCall, ToolResult] | tuple[str, str | None, ToolResult]] | list[dict[str, object]],
        parent_response_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Build a follow-up payload for multiple tool call outputs.

        Supports the current LLMService tuple shape of (call_id, response_item_id, tool_result)
        while remaining compatible with legacy ToolCall/ToolResult pair-like inputs and
        parseable response dicts when reasonable.

        Args:
            messages: Existing conversation messages to prepend to the payload.
            envelopes: Tool call/result envelopes or call/result pairs.
            parent_response_id: Optional parent response identifier for metadata.

        Returns:
            A new payload containing one output item per tool call result.
        """

        logger.info("Building multi-item follow-up payload")
        payload = list(messages) if messages is not None else []
        for envelope in envelopes:
            call_id: str | None = None
            tool_result: ToolResult | None = None
            response_item_id: str | None = None

            if isinstance(envelope, tuple):
                if len(envelope) == 3:
                    call_id, response_item_id, tool_result = envelope
                elif len(envelope) == 2:
                    first_item, second_item = envelope
                    if isinstance(first_item, ToolCall) and isinstance(second_item, ToolResult):
                        call_id = first_item.call_id if hasattr(first_item, "call_id") else first_item.tool_name
                        response_item_id = None
                        tool_result = second_item
                    elif isinstance(first_item, str) and isinstance(second_item, ToolResult):
                        call_id = first_item
                        response_item_id = None
                        tool_result = second_item
                    else:
                        parsed_call = self.parse_tool_call(first_item)
                        if parsed_call is not None and isinstance(second_item, ToolResult):
                            call_id = parsed_call.call_id if hasattr(parsed_call, "call_id") else parsed_call.tool_name
                            response_item_id = None
                            tool_result = second_item
                elif len(envelope) > 0:
                    first_item = envelope[0]
                    if isinstance(first_item, str):
                        call_id = first_item
                        response_item_id = envelope[1] if len(envelope) > 1 and isinstance(envelope[1], str) else None
                        last_item = envelope[-1]
                        if isinstance(last_item, ToolResult):
                            tool_result = last_item
                if call_id is None and tool_result is not None:
                    call_id = tool_result.tool_name
                if call_id is not None and tool_result is None:
                    tool_result = ToolResult(tool_name=call_id, success=False, output="", error="Missing tool result.")
                if call_id is not None and tool_result is not None:
                    payload_item = build_tool_call_output(call_id, tool_result)
                    logger.info("Follow-up payload item: %s", payload_item)
                    if response_item_id is not None:
                        logger.info("Follow-up payload response item id: %s", response_item_id)
                    payload.append(payload_item)
                continue

            if isinstance(envelope, ToolResult):
                call_id = envelope.tool_name
                tool_result = envelope
            elif isinstance(envelope, ToolCall):
                call_id = envelope.call_id if hasattr(envelope, "call_id") else envelope.tool_name
                tool_result = ToolResult(tool_name=envelope.tool_name, success=False, output="", error="Missing tool result.")
            else:
                parsed_call = self.parse_tool_call(envelope)
                if parsed_call is None:
                    continue
                call_id = parsed_call.call_id if hasattr(parsed_call, "call_id") else parsed_call.tool_name
                tool_result = ToolResult(tool_name=parsed_call.tool_name, success=False, output="", error="Missing tool result.")

            payload_item = build_tool_call_output(call_id, tool_result)
            logger.info("Follow-up payload item: %s", payload_item)
            payload.append(payload_item)
        logger.info("Multi-item follow-up payload built")
        return payload

    def build_litellm_tools(self) -> list[dict[str, object]]:
        """Export registered tools as LiteLLM/OpenAI function tool schemas."""

        tools: list[dict[str, object]] = []
        for tool in self.list_tools().values():
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )
        return tools

    def build_responses_tools(self) -> list[dict[str, object]]:
        """Export registered tools as Responses-style flat tool schemas."""

        tools: list[dict[str, object]] = []
        for tool in self.list_tools().values():
            tools.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            )
        return tools

    def should_continue_after_tool_call(self, value: ToolCall | ToolResult | object) -> bool:
        """Determine whether execution should continue after a tool call or response."""

        if isinstance(value, ToolCall):
            return True
        if isinstance(value, ToolResult):
            return value.success
        parsed = self.parse_tool_call(value)
        return parsed is not None

    def register_tool(self, tool: ToolDefinition, handler: Callable[..., str]) -> bool:
        """Register a tool through the registry."""

        logger.info("Registering tool: %s", tool.name)
        registered = self._tool_registry.register(tool, handler)
        logger.info("Tool registration %s: %s", "succeeded" if registered else "failed", tool.name)
        return registered

    def unregister_tool(self, tool_name: str) -> bool:
        """Unregister a tool through the registry."""

        return self._tool_registry.unregister(tool_name)

    def resolve_tool(self, tool_name: str) -> ToolDefinition | None:
        """Look up a tool by name."""

        return self._tool_registry.resolve(tool_name)

    def list_tools(self) -> dict[str, ToolDefinition]:
        """Return a copy of the registered tools."""

        return self._tool_registry.list_tools()

    def _validate_arguments(
        self,
        tool: ToolDefinition,
        arguments: dict[str, object],
    ) -> dict[str, object] | None:
        """Validate arguments against a tool definition."""

        if not isinstance(arguments, dict):
            return None
        required = tool.parameters.get("required", []) if isinstance(tool.parameters, dict) else []
        if not isinstance(required, list):
            required = []
        for key in required:
            if key not in arguments:
                return None
        return dict(arguments)
