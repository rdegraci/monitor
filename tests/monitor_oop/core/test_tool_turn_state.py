"""Tests for ToolTurnState behavior."""
from __future__ import annotations

from monitor_oop.core.tool_turn_state import ToolTurnState


def test_begin_turn_clears_pending_envelopes() -> None:
    """Verify begin_turn resets the active turn state."""

    state = ToolTurnState()
    state.record_envelope(
        call_id="call_1",
        response_item_id="item_1",
        parent_response_id="response_1",
        tool_result={"output": "sunny"},
    )

    assert state.pending_count() == 1

    state.begin_turn()

    assert state.pending_count() == 0
    assert state.build_follow_up_entries() == []


def test_record_envelope_tracks_follow_up_entries() -> None:
    """Verify recorded envelopes are exposed as follow-up entries."""

    state = ToolTurnState()

    state.record_envelope(
        call_id="call_1",
        response_item_id="item_1",
        parent_response_id="response_1",
        tool_result={"output": "sunny"},
    )
    state.record_envelope(
        call_id="call_2",
        response_item_id=None,
        parent_response_id="response_2",
        tool_result={"output": "rainy"},
    )

    assert state.pending_count() == 2
    assert state.build_follow_up_entries() == [
        ("call_1", "item_1", {"output": "sunny"}),
        ("call_2", None, {"output": "rainy"}),
    ]


def test_clear_removes_all_pending_envelopes() -> None:
    """Verify clear removes all recorded envelopes."""

    state = ToolTurnState()
    state.record_envelope(
        call_id="call_1",
        response_item_id="item_1",
        parent_response_id="response_1",
        tool_result={"output": "sunny"},
    )

    assert state.pending_count() == 1

    state.clear()

    assert state.pending_count() == 0
    assert state.build_follow_up_entries() == []
