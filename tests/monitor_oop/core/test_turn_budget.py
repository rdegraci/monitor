"""Tests for turn budget tracking in Monitor OOP."""
from __future__ import annotations

from monitor_oop.core.models import Message
from monitor_oop.core.turn_budget import TurnBudgetTracker, compact_summary_filename


def test_compact_summary_filename_builds_expected_name() -> None:
    """Verify the summary filename format uses the pid and timestamp."""

    assert compact_summary_filename(1234, "2024-01-02-03-04") == "compact-1234-2024-01-02-03-04.summary"


def test_turn_budget_tracker_counts_user_turns_on_sync() -> None:
    """Verify synchronization counts only user messages as turns."""

    tracker = TurnBudgetTracker()
    messages = [
        Message(role="system", content="hello"),
        Message(role="user", content="one"),
        Message(role="assistant", content="two"),
        Message(role="user", content="three"),
    ]

    tracker.sync(messages)

    assert tracker.turn_count == 2


def test_turn_budget_tracker_reset_and_remaining() -> None:
    """Verify the tracker resets and reports remaining budget correctly."""

    tracker = TurnBudgetTracker(turn_count=3)

    assert tracker.turns_remaining(5) == 2

    tracker.increment()
    assert tracker.turn_count == 4

    tracker.reset()
    assert tracker.turn_count == 0
    assert tracker.turns_remaining(5) == 5
