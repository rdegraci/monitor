"""Conversation boundary tracking for compaction."""
from __future__ import annotations

from dataclasses import dataclass

from monitor_oop.core.models import Message


@dataclass(slots=True)
class ConversationBoundaryTracker:
    """Track safe compaction boundaries for conversational message history."""

    preserve_units: int = 2
    current_turns: int = 0

    def _is_user_message(self, message: Message) -> bool:
        """Return whether the message starts a user turn."""

        return message.role == "user"

    def _is_assistant_message(self, message: Message) -> bool:
        """Return whether the message is an assistant turn or tool-call carrier."""

        return message.role == "assistant"

    def _is_tool_message(self, message: Message) -> bool:
        """Return whether the message is a tool result message."""

        return message.role == "tool"

    def _message_tool_calls(self, message: Message) -> list[object]:
        """Return the tool call list for a message when available."""

        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls is None:
            return []
        return list(tool_calls)

    def _tool_call_ids(self, message: Message) -> set[str]:
        """Return tool call identifiers carried by an assistant message."""

        tool_call_ids: set[str] = set()
        for tool_call in self._message_tool_calls(message):
            tool_call_id = getattr(tool_call, "id", None)
            if tool_call_id is None and isinstance(tool_call, dict):
                tool_call_id = tool_call.get("id")
            if tool_call_id is not None:
                tool_call_ids.add(str(tool_call_id))
        return tool_call_ids

    def _tool_result_id(self, message: Message) -> str | None:
        """Return the matching tool call identifier for a tool result message."""

        tool_call_id = getattr(message, "tool_call_id", None)
        if tool_call_id is None:
            return None
        return str(tool_call_id)

    def _is_tool_call_assistant_message(self, message: Message) -> bool:
        """Return whether an assistant message carries tool calls."""

        return self._is_assistant_message(message) and bool(self._message_tool_calls(message))

    def _expand_tail_boundary(self, messages: list[Message], index: int) -> int:
        """Expand a tail boundary to include complete assistant/tool clusters.

        Args:
            messages: The full conversation history in chronological order.
            index: The index of the last message in the tail candidate.

        Returns:
            The index of the earliest message that must be preserved.
        """

        while index >= 0 and self._is_tool_message(messages[index]):
            index -= 1
        if index < 0:
            return 0
        if self._is_assistant_message(messages[index]):
            start = index
            while start - 1 >= 0 and self._is_tool_message(messages[start - 1]):
                start -= 1
            if start - 1 >= 0 and self._is_tool_call_assistant_message(messages[start - 1]):
                start -= 1
                expected_tool_call_ids = self._tool_call_ids(messages[start])
                while start - 1 >= 0 and self._is_tool_message(messages[start - 1]):
                    previous_tool_message = messages[start - 1]
                    previous_tool_call_id = self._tool_result_id(previous_tool_message)
                    if expected_tool_call_ids and previous_tool_call_id not in expected_tool_call_ids:
                        break
                    start -= 1
                if start - 1 >= 0 and self._is_user_message(messages[start - 1]):
                    return start - 1
                return start
            if start - 1 >= 0 and self._is_user_message(messages[start - 1]):
                return start - 1
            return start
        if self._is_tool_call_assistant_message(messages[index]):
            start = index
            expected_tool_call_ids = self._tool_call_ids(messages[index])
            while start - 1 >= 0 and self._is_tool_message(messages[start - 1]):
                previous_tool_message = messages[start - 1]
                previous_tool_call_id = self._tool_result_id(previous_tool_message)
                if expected_tool_call_ids and previous_tool_call_id not in expected_tool_call_ids:
                    break
                start -= 1
            if start - 1 >= 0 and self._is_user_message(messages[start - 1]):
                return start - 1
            return start
        return index

    def sync(self, messages: list[Message]) -> int:
        """Synchronize the tracker with the provided message history.

        Args:
            messages: The full conversation history in chronological order.

        Returns:
            The number of user turns in the history.
        """

        self.current_turns = self.count_user_turns(messages)
        return self.current_turns

    def turns_remaining(self, budget: int) -> int:
        """Return how many turns can still be preserved within the budget.

        Args:
            budget: The total turn budget available for preservation.

        Returns:
            The remaining number of turns after accounting for tracked turns.
        """

        return max(0, budget - self.current_turns)

    def preserved_tail(self, messages: list[Message], keep_units: int) -> list[Message]:
        """Return the most recent complete units from the history.

        Args:
            messages: The full conversation history in chronological order.
            keep_units: The number of complete units to preserve from the tail.

        Returns:
            A suffix containing complete user/assistant/tool units only.
        """

        if keep_units <= 0 or not messages:
            return []
        preserved: list[list[Message]] = []
        index = len(messages) - 1
        while index >= 0 and len(preserved) < keep_units:
            unit_end = index
            unit_start = self._expand_tail_boundary(messages, index)
            preserved.append(messages[unit_start : unit_end + 1])
            index = unit_start - 1
        preserved.reverse()
        flattened: list[Message] = []
        for unit in preserved:
            flattened.extend(unit)
        return flattened

    def group_tail_for_preservation(self, messages: list[Message]) -> list[Message]:
        """Return a suffix that preserves complete conversational units.

        Args:
            messages: The full conversation history in chronological order.

        Returns:
            A suffix of the history containing the most recent complete units.
        """

        return self.preserved_tail(messages, self.preserve_units)

    def count_user_turns(self, messages: list[Message]) -> int:
        """Count user turns in the provided history.

        Args:
            messages: The full conversation history in chronological order.

        Returns:
            The number of user messages in the history.
        """

        return sum(1 for message in messages if self._is_user_message(message))
