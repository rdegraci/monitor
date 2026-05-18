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
    assert tracker.turns_remaining(2) == 0


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

    assert any(message.role == "assistant" and message.content == "calling tool" and message.tool_calls == [tool_call] for message in preserved)
    assert any(message.role == "tool" and message.content == "sunny" and message.tool_call_id == "call-1" for message in preserved)
    assert any(message.role == "assistant" and message.content == "it is sunny" and message.tool_calls is None for message in preserved)


def test_group_tail_for_preservation_uses_configured_preserve_units() -> None:
    """Verify the configured preserve_units value is used by the convenience helper."""

    tracker = ConversationBoundaryTracker(preserve_units=2)
    messages = [
        Message(role="user", content="one"),
        Message(role="assistant", content="two"),
        Message(role="user", content="three"),
        Message(role="assistant", content="four"),
    ]

    tracker.sync(messages)
    preserved = tracker.group_tail_for_preservation(messages)

    assert tracker.turns_remaining(2) == 0
    assert [message.content for message in preserved] == ["one", "two", "three", "four"]


def test_preserved_tail_keeps_tool_call_assistant_tool_result_final_assistant_intact() -> None:
    """Verify a tool-call assistant turn with tool result and final assistant stays intact."""

    tracker = ConversationBoundaryTracker(preserve_units=1)
    tool_call = ToolCall(id="call-1", name="weather", arguments="{}")
    messages = [
        Message(role="user", content="weather?"),
        Message(role="assistant", content="calling tool", tool_calls=[tool_call]),
        Message(role="tool", content="sunny", tool_call_id="call-1"),
        Message(role="assistant", content="it is sunny"),
    ]

    preserved = tracker.preserved_tail(messages, keep_units=1)

    assert any(message.role == "assistant" and message.content == "calling tool" and message.tool_calls == [tool_call] for message in preserved)
    assert any(message.role == "tool" and message.content == "sunny" and message.tool_call_id == "call-1" for message in preserved)
    assert any(message.role == "assistant" and message.content == "it is sunny" and message.tool_calls is None for message in preserved)


def test_preserved_tail_keeps_bare_user_at_tail_with_prior_assistant() -> None:
    """Verify a bare user message at the tail is preserved alongside the prior paired turn.

    Proactive compaction (compaction-before-LLM) appends the user message and
    triggers compaction before the assistant reply exists. The boundary tracker
    must treat the bare user as its own unit and still pull in the prior
    user/assistant pair as the second unit.
    """

    tracker = ConversationBoundaryTracker(preserve_units=2)
    messages = [
        Message(role="user", content="old one"),
        Message(role="assistant", content="old reply"),
        Message(role="user", content="prev"),
        Message(role="assistant", content="prev reply"),
        Message(role="user", content="now"),
    ]

    preserved = tracker.preserved_tail(messages, keep_units=2)

    assert [message.content for message in preserved] == [
        "prev",
        "prev reply",
        "now",
    ]


def test_preserved_tail_keeps_lone_bare_user_when_no_prior_turn_exists() -> None:
    """Verify the first-ever bare user message survives compaction as the only unit."""

    tracker = ConversationBoundaryTracker(preserve_units=2)
    messages = [Message(role="user", content="now")]

    preserved = tracker.preserved_tail(messages, keep_units=2)

    assert [message.content for message in preserved] == ["now"]


def test_preserved_tail_keeps_bare_user_after_tool_call_cluster() -> None:
    """Verify a bare user at the tail does not fragment a preceding tool-call cluster."""

    tracker = ConversationBoundaryTracker(preserve_units=2)
    tool_call = ToolCall(id="call-1", name="weather", arguments="{}")
    messages = [
        Message(role="user", content="weather?"),
        Message(role="assistant", content="calling tool", tool_calls=[tool_call]),
        Message(role="tool", content="sunny", tool_call_id="call-1"),
        Message(role="assistant", content="it is sunny"),
        Message(role="user", content="thanks"),
    ]

    preserved = tracker.preserved_tail(messages, keep_units=2)

    assert [message.content for message in preserved] == [
        "weather?",
        "calling tool",
        "sunny",
        "it is sunny",
        "thanks",
    ]
    preserved_tool_calls = next(
        message.tool_calls for message in preserved if message.content == "calling tool"
    )
    assert preserved_tool_calls == [tool_call]
