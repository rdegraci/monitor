"""Request-building helpers for Monitor OOP LLM flows."""
from __future__ import annotations

import logging
from typing import Any

from monitor_oop.core.models import Message

logger = logging.getLogger(__name__)


class LLMRequestBuilder:
    """Build adapter-ready request inputs for LLM completions."""

    def __init__(
        self,
        prompt_text: str | None = None,
    ) -> None:
        """Initialize a request builder.

        Args:
            prompt_text: Optional injected system prompt text.
        """

        self._prompt_text = prompt_text

    def build_input(
        self,
        history: list[str | Message],
        prompt_text: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build request input from conversation history.

        The latest user message must already be the last entry in ``history``.
        This avoids the prior contract of appending a separate ``user_input``
        on top, which silently duplicated the user message in the request.

        Tool-call metadata (``tool_calls``, ``tool_call_id``, ``name``) on
        Message instances is emitted alongside ``role``/``content`` so the
        boundary tracker's careful preservation of tool clusters survives
        through the request layer.

        Args:
            history: Conversation items as strings or Message objects, with
                the current user turn as the final entry.
            prompt_text: Optional injected system prompt text.

        Returns:
            A list of request messages suitable for adapter consumption.
        """

        input_messages: list[dict[str, Any]] = []
        resolved_prompt_text = self._resolve_prompt_text(prompt_text)
        if resolved_prompt_text is not None:
            input_messages.append({"role": "system", "content": resolved_prompt_text})
        input_messages.extend(self._history_items_to_request_messages(history))
        return input_messages

    def build_summarization_input(
        self,
        prompt_text: str,
        message_history: list[Message],
    ) -> list[dict[str, str]]:
        """Build request input for summary generation.

        The summary token cap is enforced by the response client via
        ``max_output_tokens`` rather than as a soft string hint here.

        Args:
            prompt_text: The summary prompt text.
            message_history: Prior conversation messages to summarize.

        Returns:
            A list of request messages suitable for adapter consumption.
        """

        input_messages: list[dict[str, str]] = [
            {"role": "system", "content": prompt_text}
        ]
        for item in message_history:
            input_messages.append({"role": item.role, "content": item.content})
        return input_messages

    def strip_provider_prefix(self, model: str) -> str:
        """Remove a provider prefix from a model name when present.

        Args:
            model: The configured model name.

        Returns:
            The model name without a leading `provider/` prefix.
        """

        return self._strip_provider_prefix(model)

    def _resolve_prompt_text(self, prompt_text: str | None = None) -> str | None:
        if prompt_text is not None:
            return prompt_text
        return self._prompt_text

    def _history_items_to_request_messages(
        self,
        history: list[str | Message],
    ) -> list[dict[str, Any]]:
        request_messages: list[dict[str, Any]] = []
        for item in history:
            if isinstance(item, Message):
                request_messages.append(self._message_to_request_dict(item))
            elif isinstance(item, str):
                request_messages.append({"role": "user", "content": item})
        return request_messages

    def _message_to_request_dict(self, message: Message) -> dict[str, Any]:
        """Convert a Message dataclass to a request dict.

        Optional tool-related fields are included only when set so messages
        without tool metadata serialize as the original ``{role, content}``
        shape and existing callers/snapshots keep working.
        """

        request_message: dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }
        if message.name is not None:
            request_message["name"] = message.name
        if message.tool_call_id is not None:
            request_message["tool_call_id"] = message.tool_call_id
        if message.tool_calls is not None:
            request_message["tool_calls"] = [
                self._serialize_tool_call(tool_call) for tool_call in message.tool_calls
            ]
        return request_message

    def _serialize_tool_call(self, tool_call: Any) -> dict[str, Any]:
        """Serialize a tool call (dataclass or dict) into a plain dict."""

        if isinstance(tool_call, dict):
            return dict(tool_call)
        serialized: dict[str, Any] = {}
        for field_name in ("id", "name", "arguments"):
            value = getattr(tool_call, field_name, None)
            if value is not None:
                serialized[field_name] = value
        return serialized

    def _strip_provider_prefix(self, model: str) -> str:
        if "/" in model:
            return model.split("/", 1)[1]
        return model
