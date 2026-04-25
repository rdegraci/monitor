"""Tool parsing helpers for Monitor OOP."""
from __future__ import annotations

import json
from typing import Any

from monitor_oop.core.tools.tool_models import ToolCall, ToolResult


def normalize_tool_arguments(raw_arguments: object) -> dict[str, object]:
    """Normalize raw tool arguments into a dictionary."""

    if raw_arguments is None:
        return {}
    if isinstance(raw_arguments, dict):
        return dict(raw_arguments)
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def extract_first_tool_call(output: object) -> ToolCall | None:
    """Extract the first tool call from a response output list."""

    if not isinstance(output, list):
        return None
    for item in output:
        if isinstance(item, dict):
            item_type = item.get("type")
            call_id = item.get("call_id") or item.get("id")
            tool_name = item.get("name") or item.get("tool") or item.get("tool_name")
            raw_arguments = item.get("arguments")
        else:
            item_type = getattr(item, "type", None)
            call_id = getattr(item, "call_id", None) or getattr(item, "id", None)
            tool_name = getattr(item, "name", None) or getattr(item, "tool", None) or getattr(item, "tool_name", None)
            raw_arguments = getattr(item, "arguments", None)
        if item_type not in {"function_call", "tool_call"}:
            continue
        if not call_id or not tool_name:
            continue
        arguments = normalize_tool_arguments(raw_arguments)
        return ToolCall(call_id=str(call_id), tool_name=str(tool_name), arguments=arguments)
    return None


def parse_tool_call(response: object) -> ToolCall | None:
    """Parse a tool call from a model response if present."""

    output = getattr(response, "output", response)
    return extract_first_tool_call(output)


def build_tool_call_output(call_id: str, result: ToolResult) -> dict[str, Any]:
    """Build a tool-call output payload for the model follow-up."""

    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": result.output if result.success else result.error,
    }


def should_continue_after_tool_call(response_or_tool_call: object) -> bool:
    """Return whether more tool work is needed from a response or tool call."""

    if isinstance(response_or_tool_call, ToolCall):
        return True
    return parse_tool_call(response_or_tool_call) is not None
