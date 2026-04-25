"""Conversation history service for Monitor OOP."""
from __future__ import annotations

from .models import History, Message


class HistoryService:
    """Owns in-memory conversation history for one runtime."""

    def __init__(self, config_service) -> None:
        self.config_service = config_service
        self.history = History()

    def _snapshot(self) -> list[Message]:
        """Return a snapshot of the stored conversation messages."""

        return self.history.snapshot()

    @property
    def messages(self) -> list[Message]:
        """Compatibility view of the current history messages."""

        return self._snapshot()

    def snapshot(self) -> list[Message]:
        """Return a copy of the current history messages."""

        return self._snapshot()

    def initialize(self) -> None:
        """Initialize history storage."""

        return None

    def append(self, item: Message) -> None:
        """Append a message to history."""

        self.history.append(item)

    def clear(self) -> None:
        """Clear stored history."""

        self.history.clear()

    def flush(self) -> None:
        """Flush stored history."""

        return None

    def trim(self, count: int) -> None:
        """Trim messages to the newest ``count`` entries."""

        self.history.trim(count)

    def summarize_if_needed(self) -> bool:
        """Summarize history when needed."""

        return False

    def _reset_with_summary(self, summary_text: str) -> None:
        """Reset history while preserving a summary message."""

        self.history.clear()
        self.history.append(Message(role="system", content=summary_text))

    def reset_with_summary(self, summary_text: str) -> None:
        """Reset history while preserving a summary message."""

        self._reset_with_summary(summary_text)
