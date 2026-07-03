"""Ollama response adaptation helpers.

This module converts native Ollama Python client responses into the legacy
OpenAI/LiteLLM-style response shape expected by the rest of the runtime.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any


logger = logging.getLogger(__name__)


def adapt_ollama_chat_response(response: Any) -> dict[str, Any]:
    """Convert a native Ollama chat response to the legacy completion shape.

    Args:
        response: Native Ollama response object or mapping.

    Returns:
        A dictionary with ``choices[0].message.content`` populated when possible.
    """
    logger.info("Ollama response shape: %s", _describe_shape(response))
    message = _extract_message(response)
    content = _extract_content(message)
    logger.info("Ollama response content: %r", content)
    logger.info("Ollama response raw message payload: %r", message)
    logger.info("Ollama response return payload: %r", response)
    tool_calls = _extract_tool_calls(message)
    result: dict[str, Any] = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": _extract_finish_reason(response, tool_calls),
            }
        ]
    }
    if tool_calls:
        result["choices"][0]["message"]["tool_calls"] = tool_calls
    usage = _extract_usage(response)
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


def _extract_message(response: Any) -> Any:
    """Extract the native message payload from an Ollama response."""
    if isinstance(response, dict):
        return response.get("message")
    return getattr(response, "message", None)


def _extract_content(message: Any) -> str:
    """Extract assistant content from a native Ollama message payload."""
    if isinstance(message, dict):
        content = message.get("content")
    else:
        content = getattr(message, "content", None)
    if content is None:
        return ""
    return str(content)


def _extract_tool_calls(message: Any) -> list[dict[str, Any]]:
    """Extract Ollama tool-call payloads when present."""
    if isinstance(message, dict):
        tool_calls = message.get("tool_calls")
    else:
        tool_calls = getattr(message, "tool_calls", None)
    if not isinstance(tool_calls, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, tool_call in enumerate(tool_calls):
        normalized_tool_call = _normalize_tool_call(tool_call, index)
        if normalized_tool_call is not None:
            normalized.append(normalized_tool_call)
    return normalized


def _normalize_tool_call(tool_call: Any, index: int) -> dict[str, Any] | None:
    """Normalize a single Ollama tool call to the legacy OpenAI-style shape.

    Args:
        tool_call: Native Ollama tool-call object or mapping.
        index: Zero-based tool-call position within the assistant message.

    Returns:
        A normalized tool-call dictionary, or ``None`` when the payload cannot
        be adapted.
    """
    if isinstance(tool_call, dict):
        tool_call_dict = dict(tool_call)
    else:
        tool_call_dict = {
            key: value
            for key, value in vars(tool_call).items()
            if not key.startswith("_")
        }
    function_payload = tool_call_dict.get("function")
    normalized_function = _normalize_tool_call_function(function_payload)
    if normalized_function is None:
        logger.warning("Skipping Ollama tool call without function payload at index=%s", index)
        return None
    tool_call_id = tool_call_dict.get("id")
    if not isinstance(tool_call_id, str) or not tool_call_id.strip():
        tool_call_id = _generate_tool_call_id(index)
    return {
        "id": tool_call_id,
        "type": "function",
        "function": normalized_function,
    }


def _normalize_tool_call_function(function_payload: Any) -> dict[str, Any] | None:
    """Normalize an Ollama function payload to the legacy shape.

    Args:
        function_payload: Native Ollama function payload object or mapping.

    Returns:
        A dictionary containing a function ``name`` and serialized ``arguments``,
        or ``None`` when the payload is missing required fields.
    """
    if isinstance(function_payload, dict):
        function_dict = dict(function_payload)
    elif function_payload is None:
        return None
    else:
        function_dict = {
            key: value
            for key, value in vars(function_payload).items()
            if not key.startswith("_")
        }
    function_name = function_dict.get("name")
    if not isinstance(function_name, str) or not function_name.strip():
        return None
    return {
        "name": function_name,
        "arguments": function_dict.get("arguments", {}),
    }


def _generate_tool_call_id(index: int) -> str:
    """Generate a stable fallback tool-call identifier.

    Args:
        index: Zero-based tool-call position within the assistant message.

    Returns:
        A non-empty identifier suitable for legacy tool-call validation.
    """
    return f"ollama-tool-{index}-{uuid.uuid4().hex}"


def _extract_finish_reason(response: Any, tool_calls: list[dict[str, Any]]) -> str:
    """Extract a best-effort finish reason from a native Ollama response."""
    if tool_calls:
        return "tool_calls"
    if isinstance(response, dict):
        done_reason = response.get("done_reason")
        done = response.get("done")
    else:
        done_reason = getattr(response, "done_reason", None)
        done = getattr(response, "done", None)
    if isinstance(done_reason, str) and done_reason.strip():
        return done_reason
    if done is True:
        return "stop"
    return "stop"


def _extract_usage(response: Any) -> dict[str, Any] | None:
    """Extract usage metadata from a native Ollama response when available."""
    if isinstance(response, dict):
        usage = response.get("usage")
    else:
        usage = getattr(response, "usage", None)
    if isinstance(usage, dict):
        return usage
    return None
