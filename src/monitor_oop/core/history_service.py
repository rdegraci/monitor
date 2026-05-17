"""Conversation history service for Monitor OOP."""
from __future__ import annotations

import logging

from monitor_oop.core.models import History, Message
from monitor_oop.core.turn_budget import TurnBudgetTracker
from monitor_oop.core.conversation_boundary_tracker import (
    ConversationBoundaryTracker,
)

logger = logging.getLogger(__name__)

COMPACTION_THRESHOLD_RATIO = 0.1


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
        self._conversation_boundary_tracker = ConversationBoundaryTracker()

    def _snapshot(self) -> list[Message]:
        """Return a snapshot of the stored conversation messages."""

        return self._history.snapshot()

    def _recent_messages(self, keep_turns: int) -> list[Message]:
        """Return the newest messages to preserve during compaction.

        Preserved tail entries should respect complete conversation units and
        tool-call clusters when the boundary tracker can identify them.
        """

        messages = self._history.snapshot()
        if keep_turns <= 0:
            return []
        return self._conversation_boundary_tracker.preserved_tail(
            messages,
            keep_turns,
        )

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

    def append_message(self, message: Message) -> None:
        """Append an enriched message to history."""

        self._history.append(message)
        snapshot = self._history.snapshot()
        self._turn_budget_tracker.sync(snapshot)
        self._conversation_boundary_tracker.sync(snapshot)

    def append(self, item: Message) -> None:
        """Append a message to history."""

        self.append_message(item)

    def clear(self) -> None:
        """Clear stored history."""

        self._history.clear()
        snapshot = self._history.snapshot()
        self._turn_budget_tracker.sync(snapshot)
        self._conversation_boundary_tracker.sync(snapshot)

    def trim(self, count: int) -> None:
        """Trim messages to the newest ``count`` entries."""

        self._history.trim(count)
        snapshot = self._history.snapshot()
        self._turn_budget_tracker.sync(snapshot)
        self._conversation_boundary_tracker.sync(snapshot)

    def should_compact(
        self,
        context_window: int | None = None,
        estimated_token_count: int | None = None,
        message_lengths: list[int] | None = None,
        output_window: int | None = None,
    ) -> bool:
        """Return whether the stored history should be compacted.

        Compaction is evaluated in this order:

        1. Context-window pressure, using estimated input tokens plus reserved
           output headroom when available.
        2. Token pressure, when ``estimated_token_count`` is provided.
        3. Turn-budget pressure, preserving the existing threshold ratio
           behavior for legacy callers.
        4. Raw message-length heuristics, when ``message_lengths`` are provided.

        When only the legacy inputs are available, the turn-budget threshold
        ratio behavior is unchanged.
        """

        messages = self._history.snapshot()

        if context_window is not None:
            current_tokens = sum(message_lengths or [])
            reserved_output_tokens = output_window or 0
            context_tokens = current_tokens + reserved_output_tokens
            if context_tokens >= context_window:
                logger.info(
                    "Compaction triggered by context-window pressure with output headroom: input_tokens=%s reserved_output_tokens=%s context_tokens=%s context_window=%s",
                    current_tokens,
                    reserved_output_tokens,
                    context_tokens,
                    context_window,
                )
                return True

        if estimated_token_count is not None:
            current_tokens = sum(message_lengths) if message_lengths is not None else len(messages)
            if current_tokens >= estimated_token_count:
                logger.info(
                    "Compaction triggered by token pressure: current_tokens=%s estimated_token_count=%s",
                    current_tokens,
                    estimated_token_count,
                )
                return True

        max_turns = self._config_service.get_conversation_turn_budget()
        if max_turns is not None:
            turns_remaining = self._conversation_boundary_tracker.turns_remaining(
                max_turns
            )
            compact_threshold = max_turns * COMPACTION_THRESHOLD_RATIO
            if turns_remaining < compact_threshold:
                logger.info(
                    "Compaction triggered by turn-budget pressure: turns_remaining=%s compact_threshold=%s max_turns=%s",
                    turns_remaining,
                    compact_threshold,
                    max_turns,
                )
                return True

        if message_lengths is not None:
            total_length = sum(message_lengths)
            if total_length > 0:
                logger.info(
                    "Compaction triggered by message-length heuristic: total_length=%s message_count=%s",
                    total_length,
                    len(message_lengths),
                )
                return True

        return False

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

        keep_turns = 2
        recent_messages = self._conversation_boundary_tracker.preserved_tail(
            self._history.snapshot(),
            keep_turns,
        )

        self._history.clear()
        self._history.append(Message(role="system", content=summary_text))
        for message in recent_messages:
            self._history.append(message)
        snapshot = self._history.snapshot()
        self._turn_budget_tracker.sync(snapshot)
        self._conversation_boundary_tracker.sync(snapshot)
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
        snapshot = self._history.snapshot()
        self._turn_budget_tracker.sync(snapshot)
        self._conversation_boundary_tracker.sync(snapshot)

    def reset_with_summary(self, summary_text: str) -> None:
        """Reset history while preserving a summary message."""

        return self._reset_with_summary(summary_text)
