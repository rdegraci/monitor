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


def _extract_tool_call_from_mapping(item: dict[str, object]) -> ToolCall | None:
    """Extract a tool call from a mapping with conservative shape checks."""

    item_type = item.get("type")
    if item_type not in {"function_call", "tool_call"}:
        return None
    call_id = item.get("call_id") or item.get("id")
    response_item_id = item.get("id")
    tool_name = item.get("name") or item.get("tool") or item.get("tool_name")
    raw_arguments = item.get("arguments")
    if call_id and tool_name:
        arguments = normalize_tool_arguments(raw_arguments)
        return ToolCall(
            call_id=str(call_id),
            response_item_id=str(response_item_id) if response_item_id is not None else None,
            tool_name=str(tool_name),
            arguments=arguments,
        )

    return None


def _extract_tool_call_from_object(item: object) -> ToolCall | None:
    """Extract a tool call from an object with conservative shape checks."""

    item_type = getattr(item, "type", None)
    if item_type in {"function_call", "tool_call"}:
        call_id = getattr(item, "call_id", None) or getattr(item, "id", None)
        response_item_id = getattr(item, "id", None)
        tool_name = getattr(item, "name", None) or getattr(item, "tool", None) or getattr(item, "tool_name", None)
        raw_arguments = getattr(item, "arguments", None)
        if call_id and tool_name:
            arguments = normalize_tool_arguments(raw_arguments)
            return ToolCall(
                call_id=str(call_id),
                response_item_id=str(response_item_id) if response_item_id is not None else None,
                tool_name=str(tool_name),
                arguments=arguments,
            )

    return None


def extract_tool_calls(output: object) -> list[ToolCall]:
    """Extract all tool calls from a response output list."""

    if not isinstance(output, list):
        return []
    tool_calls: list[ToolCall] = []
    for item in output:
        if isinstance(item, dict):
            tool_call = _extract_tool_call_from_mapping(item)
        else:
            tool_call = _extract_tool_call_from_object(item)
        if tool_call is not None:
            tool_calls.append(tool_call)
    return tool_calls


def extract_tool_calls_from_response(response_or_output: object) -> list[ToolCall]:
    """Extract all tool calls from a response object or output list."""

    output = getattr(response_or_output, "output", response_or_output)
    return extract_tool_calls(output)


def parse_tool_calls(response_or_output: object) -> list[ToolCall]:
    """Parse all tool calls from a response object or output list."""

    return extract_tool_calls_from_response(response_or_output)


def extract_first_tool_call(output: object) -> ToolCall | None:
    """Extract the first tool call from a response output list."""

    tool_calls = extract_tool_calls(output)
    if tool_calls:
        return tool_calls[0]
    return None


def parse_tool_call(response: object) -> ToolCall | None:
    """Parse a tool call from a model response if present."""

    tool_calls = extract_tool_calls_from_response(response)
    if tool_calls:
        return tool_calls[0]
    return None


def build_tool_call_output(
    call_id: str,
    result: ToolResult,
    response_item_id: str | None = None,
    parent_response_id: str | None = None,
) -> dict[str, Any]:
    """Build a tool-call output payload for the model follow-up.

    The payload id is intentionally omitted to avoid duplicate item IDs in
    Responses API follow-up requests.
    """

    output_item: dict[str, Any] = {
        "type": "function_call_output",
        "call_id": call_id,
        "output": result.output if result.success else result.error,
    }
    if not result.success:
        output_item["error"] = result.error
    return output_item


def should_continue_after_tool_call(response_or_tool_call: object) -> bool:
    """Return whether more tool work is needed from a response or tool call."""

    if isinstance(response_or_tool_call, ToolCall):
        return True
    return parse_tool_call(response_or_tool_call) is not None
