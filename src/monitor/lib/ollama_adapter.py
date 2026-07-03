"""Ollama response adaptation helpers.

This module converts native Ollama Python client responses into the legacy
OpenAI/LiteLLM-style response shape expected by the rest of the runtime.
"""

from __future__ import annotations

import logging
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
    tool_calls = _extract_tool_calls(message)
    result: dict[str, Any] = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": _extract_finish_reason(response),
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
    for tool_call in tool_calls:
        if isinstance(tool_call, dict):
            normalized.append(tool_call)
        else:
            normalized.append({"id": getattr(tool_call, "id", None)})
    return normalized


def _extract_finish_reason(response: Any) -> str:
    """Extract a best-effort finish reason from a native Ollama response."""
    if isinstance(response, dict):
        done = response.get("done")
    else:
        done = getattr(response, "done", None)
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
