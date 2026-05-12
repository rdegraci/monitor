"""Turn budget tracking for Monitor OOP conversation compaction."""
from __future__ import annotations

from dataclasses import dataclass

from monitor_oop.core.models import Message


def compact_summary_filename(pid: int, timestamp: str) -> str:
    """Compute a compact summary filename from a pid and timestamp string.

    Args:
        pid: The process identifier.
        timestamp: A timestamp string in a compact date-time format.

    Returns:
        A filename in the form compact-<pid>-YYYY-MM-DD-HH-MM.summary.
    """

    return f"compact-{pid}-{timestamp}.summary"


@dataclass(slots=True)
class TurnBudgetTracker:
    """Track conversation turns against a configured budget.

    Attributes:
        turn_count: The number of turns that have been consumed.
    """

    turn_count: int = 0

    def increment(self) -> None:
        """Increment the tracked turn count by one."""

        self.turn_count += 1

    def reset(self) -> None:
        """Reset the tracked turn count to zero."""

        self.turn_count = 0

    def turns_remaining(self, budget: int) -> int:
        """Return the number of turns remaining for a given budget.

        Args:
            budget: The maximum allowed number of turns.

        Returns:
            The remaining turns, never less than zero.
        """

        return max(budget - self.turn_count, 0)

    def sync(self, messages: list[Message]) -> None:
        """Synchronize the turn count from the current history snapshot.

        Args:
            messages: The messages currently stored in conversation history.
        """

        self.turn_count = sum(1 for message in messages if message.role == "user")
