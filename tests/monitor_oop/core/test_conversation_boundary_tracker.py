"""Tests for ConversationBoundaryTracker behavior."""
from __future__ import annotations

from monitor_oop.core.conversation_boundary_tracker import ConversationBoundaryTracker
from monitor_oop.core.models import Message, ToolCall


def test_count_user_turns_counts_only_user_messages() -> None:
    """Verify user turn counting ignores assistant and tool messages."""

    tracker = ConversationBoundaryTracker()
    messages = [
        Message(role="user", content="one"),
        Message(role="assistant", content="two"),
        Message(role="tool", content="three", tool_call_id="call-1"),
        Message(role="user", content="four"),
    ]

    assert tracker.count_user_turns(messages) == 2


def test_sync_updates_current_turn_count() -> None:
    """Verify sync stores the current user turn count."""

    tracker = ConversationBoundaryTracker()
    messages = [
        Message(role="user", content="one"),
        Message(role="assistant", content="two"),
        Message(role="user", content="three"),
    ]

    assert tracker.sync(messages) == 2
    assert tracker.current_turns == 2


def test_preserved_tail_keeps_recent_plain_conversation_units() -> None:
    """Verify the tracker preserves the most recent plain conversation units."""

    tracker = ConversationBoundaryTracker(preserve_units=2)
    messages = [
        Message(role="user", content="one"),
        Message(role="assistant", content="two"),
        Message(role="user", content="three"),
        Message(role="assistant", content="four"),
        Message(role="user", content="five"),
        Message(role="assistant", content="six"),
    ]

    preserved = tracker.preserved_tail(messages, keep_units=2)

    assert [message.content for message in preserved] == ["three", "four", "five", "six"]


def test_preserved_tail_keeps_tool_cluster_attached_to_assistant_turn() -> None:
    """Verify tool results stay attached to the assistant turn that produced them."""

    tracker = ConversationBoundaryTracker(preserve_units=1)
    tool_call = ToolCall(id="call-1", name="weather", arguments="{}")
    messages = [
        Message(role="user", content="weather?"),
        Message(role="assistant", content="calling tool", tool_calls=[tool_call]),
        Message(role="tool", content="sunny", tool_call_id="call-1"),
        Message(role="assistant", content="it is sunny"),
    ]

    preserved = tracker.preserved_tail(messages, keep_units=1)

    assert [message.role for message in preserved] == ["tool", "assistant"]
    assert [message.content for message in preserved] == ["sunny", "it is sunny"]
    assert preserved[0].tool_call_id == "call-1"
    assert preserved[1].tool_calls is None


def test_group_tail_for_preservation_uses_configured_preserve_units() -> None:
    """Verify the configured preserve_units value is used by the convenience helper."""

    tracker = ConversationBoundaryTracker(preserve_units=2)
    messages = [
        Message(role="user", content="one"),
        Message(role="assistant", content="two"),
        Message(role="user", content="three"),
        Message(role="assistant", content="four"),
    ]

    preserved = tracker.group_tail_for_preservation(messages)

    assert [message.content for message in preserved] == ["one", "two", "three", "four"]
