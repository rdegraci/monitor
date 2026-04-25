"""Conversation history service for Monitor OOP."""
from __future__ import annotations

from .models import History, Message


class HistoryService:
    """Owns in-memory conversation history for one runtime."""

    def __init__(self, config_service) -> None:
        self.config_service = config_service
        self.history = History()

    @property
    def messages(self) -> list[str | Message]:
        """Return the stored conversation messages."""

        return self.history.messages

    def initialize(self) -> None:
        """Initialize history storage."""

        return None

    def append(self, item) -> None:
        """Append a message to history."""

        self.history.messages.append(item)

    def flush(self) -> None:
        """Flush stored history."""

        return None

    def trim(self, count: int) -> None:
        """Trim messages to the newest ``count`` entries."""

        self.history.messages = self.history.messages[-count:]

    def summarize_if_needed(self) -> bool:
        """Summarize history when needed."""

        return False

    def reset_with_summary(self, summary_text: str) -> None:
        """Reset history while preserving a summary message."""

        self.history.messages = [Message(role="system", content=summary_text)]
