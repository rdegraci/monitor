"""Conversation history service for Monitor OOP."""
from __future__ import annotations

import logging

from monitor_oop.core.models import History, Message
from monitor_oop.core.turn_budget import TurnBudgetTracker

logger = logging.getLogger(__name__)


class HistoryService:
    """Owns in-memory conversation history for one runtime."""

    def __init__(self, config_service, compaction_store=None) -> None:
        """Initialize history storage.

        Args:
            config_service: Service providing runtime configuration.
            compaction_store: Optional disk-backed store used to persist
                compaction summaries.
        """
        self._config_service = config_service
        self._compaction_store = compaction_store
        self._history = History()
        self._turn_budget_tracker = TurnBudgetTracker()

    def _snapshot(self) -> list[Message]:
        """Return a snapshot of the stored conversation messages."""

        return self._history.snapshot()

    def _recent_messages(self, keep_turns: int) -> list[Message]:
        """Return the newest messages to preserve during compaction."""

        messages = self._history.snapshot()
        if keep_turns <= 0:
            return []
        return messages[-keep_turns:]

    def _persist_compaction_summary(self, summary_text: str) -> None:
        """Persist a compacted summary when disk-backed storage is available."""

        compaction_store = self._compaction_store
        if compaction_store is None:
            return None

        persist = getattr(compaction_store, "persist_summary", None)
        if persist is None:
            persist = getattr(compaction_store, "save_summary", None)
        if persist is None:
            return None

        try:
            persist(summary_text)
        except Exception:
            logger.exception(
                "Failed to persist compaction summary via %s",
                type(compaction_store).__name__,
            )

    @property
    def messages(self) -> list[Message]:
        """Compatibility view of the current history messages."""

        return self._snapshot()

    def snapshot(self) -> list[Message]:
        """Return a copy of the current history messages."""

        return self._snapshot()

    def append(self, item: Message) -> None:
        """Append a message to history."""

        self._history.append(item)
        self._turn_budget_tracker.sync(self._history.snapshot())

    def clear(self) -> None:
        """Clear stored history."""

        self._history.clear()
        self._turn_budget_tracker.sync(self._history.snapshot())

    def trim(self, count: int) -> None:
        """Trim messages to the newest ``count`` entries."""

        self._history.trim(count)
        self._turn_budget_tracker.sync(self._history.snapshot())

    def should_compact(self) -> bool:
        """Return whether the stored history should be compacted.

        The decision is based on ``RuntimeConfig.conversation_max_turns`` and
        counts user/assistant exchanges as turns rather than raw messages.
        """

        max_turns = self._config_service.get_conversation_turn_budget()
        if max_turns is None:
            return False

        turns_remaining = self._turn_budget_tracker.turns_remaining(max_turns)
        compact_threshold = max_turns * 0.1
        return turns_remaining <= compact_threshold

    def compact_with_summary(self, summary_text: str) -> bool:
        """Compact history into a summary plus the newest messages.

        Compaction is deterministic: it removes older messages and reinserts a
        system summary followed by the newest two messages currently stored.

        Args:
            summary_text: Summary message to insert at the start of history.

        Returns:
            True if compaction was applied, otherwise False.
        """

        if not self.should_compact():
            return False

        recent_messages = self._recent_messages(2)

        self._history.clear()
        self._history.append(Message(role="system", content=summary_text))
        for message in recent_messages:
            self._history.append(message)
        self._turn_budget_tracker.sync(self._history.snapshot())
        self._persist_compaction_summary(summary_text)
        return True

    def compact(self, summary_text: str) -> bool:
        """Compact history into a summary plus the newest messages.

        This is the public entry point for callers that already have the
        compacted summary text available.
        """

        return self.compact_with_summary(summary_text)

    def _reset_with_summary(self, summary_text: str) -> None:
        """Reset history while preserving a summary message."""

        self._history.clear()
        self._history.append(Message(role="system", content=summary_text))
        self._turn_budget_tracker.sync(self._history.snapshot())

    def reset_with_summary(self, summary_text: str) -> None:
        """Reset history while preserving a summary message."""

        self._reset_with_summary(summary_text)
