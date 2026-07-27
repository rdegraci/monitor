"""llama.cpp response adaptation helpers.

This module converts llama.cpp server chat-completions responses into the
legacy OpenAI/LiteLLM-style response shape expected by the rest of the runtime.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any


logger = logging.getLogger(__name__)


def adapt_llamacpp_chat_response(response: Any) -> dict[str, Any]:
    """Convert a llama.cpp chat-completions response to the legacy completion shape.

    Args:
        response: Parsed JSON response object from the llama.cpp server.

    Returns:
        A dictionary shaped like the legacy completion object used by the app.
    """
    logger.info("llama.cpp response shape: %s", _describe_shape(response))
    if isinstance(response, dict):
        message = _extract_message(response)
        finish_reason = _extract_finish_reason(response)
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else None
    else:
        message = None
        finish_reason = "stop"
        usage = None

    content = _extract_content(message)
    tool_calls = _extract_tool_calls(message)
    result: dict[str, Any] = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": finish_reason,
            }
        ]
    }
    if tool_calls:
        result["choices"][0]["message"]["tool_calls"] = tool_calls
    if usage is not None:
        result["usage"] = usage
    return result


def _describe_shape(value: Any) -> Any:
    """Return a lightweight recursive description of a value's shape."""
    if isinstance(value, dict):
        return {str(key): _describe_shape(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_describe_shape(item) for item in value]
    return type(value).__name__


def _extract_message(response: dict[str, Any]) -> Any:
    """Extract the assistant message from a chat-completions response."""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return None
    return first_choice.get("message")


def _extract_content(message: Any) -> str:
    """Extract assistant text content from a message payload."""
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if content is None:
        return ""
    return str(content)


def _extract_tool_calls(message: Any) -> list[dict[str, Any]]:
    """Extract normalized tool calls from a message payload."""
    if not isinstance(message, dict):
        return []
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, tool_call in enumerate(tool_calls):
        normalized_tool_call = _normalize_tool_call(tool_call, index)
        if normalized_tool_call is not None:
            normalized.append(normalized_tool_call)
    return normalized


def _normalize_tool_call(tool_call: Any, index: int) -> dict[str, Any] | None:
    """Normalize a single llama.cpp tool call to the legacy shape.

    Args:
        tool_call: Tool call payload from the llama.cpp server response.
        index: Zero-based tool-call position within the assistant message.

    Returns:
        A normalized tool-call dictionary, or ``None`` when unusable.
    """
    if not isinstance(tool_call, dict):
        return None
    function_payload = tool_call.get("function")
    normalized_function = _normalize_tool_call_function(function_payload)
    if normalized_function is None:
        logger.warning("Skipping llama.cpp tool call without function payload at index=%s", index)
        return None
    tool_call_id = tool_call.get("id")
    if not isinstance(tool_call_id, str) or not tool_call_id.strip():
        tool_call_id = _generate_tool_call_id(index)
    tool_call_type = tool_call.get("type")
    if not isinstance(tool_call_type, str) or not tool_call_type.strip():
        tool_call_type = "function"
    return {
        "id": tool_call_id,
        "type": tool_call_type,
        "function": normalized_function,
    }


def _normalize_tool_call_function(function_payload: Any) -> dict[str, Any] | None:
    """Normalize a llama.cpp function payload to the legacy shape.

    Args:
        function_payload: Function payload from a tool call.

    Returns:
        A dictionary containing the function ``name`` and ``arguments``.
    """
    if not isinstance(function_payload, dict):
        return None
    function_name = function_payload.get("name")
    if not isinstance(function_name, str) or not function_name.strip():
        return None
    arguments = function_payload.get("arguments", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            pass
    return {
        "name": function_name,
        "arguments": arguments,
    }


def _generate_tool_call_id(index: int) -> str:
    """Generate a fallback tool-call identifier.

    Args:
        index: Zero-based tool-call position within the assistant message.

    Returns:
        A non-empty identifier suitable for tool-call validation.
    """
    return f"llamacpp-tool-{index}-{uuid.uuid4().hex}"


def _extract_finish_reason(response: dict[str, Any]) -> str:
    """Extract a best-effort finish reason from the server response."""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return "stop"
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return "stop"
    finish_reason = first_choice.get("finish_reason")
    if isinstance(finish_reason, str) and finish_reason.strip():
        return finish_reason
    return "stop"
