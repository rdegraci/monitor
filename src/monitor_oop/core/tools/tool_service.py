"""Tool execution service for Monitor OOP."""
from __future__ import annotations

import logging
from collections.abc import Callable

from monitor_oop.core.tools.parsing import build_tool_call_output, parse_tool_call as _parse_tool_call
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
