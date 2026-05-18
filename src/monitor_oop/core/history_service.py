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

    def _persist_compaction_summary(self, summary_text: str) -> None:
        """Persist a compacted summary when disk-backed storage is available."""

        compaction_store = self._compaction_store
        if compaction_store is None:
            return None

        persist = getattr(compaction_store, "persist_summary", None)
        if persist is None:
            return None

        try:
            persist(summary_text)
        except OSError:
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
        output_window: int | None = None,
    ) -> bool:
        """Return whether the stored history should be compacted.

        Compaction is evaluated in this order:

        1. Soft context-window pressure: when both ``context_window`` and
           ``estimated_token_count`` are provided and ``compaction_soft_ratio``
           is configured to ``(0, 1)``, fire proactively once input tokens
           reach ``ratio × context_window`` — keeping the summarization call
           cheap and leaving headroom for fallback recovery.
        2. Hard context-window pressure: fire when input tokens plus reserved
           output headroom meet the window. This is the backstop.
        3. Turn-budget pressure: fire when remaining user-turn budget falls
           below ``COMPACTION_THRESHOLD_RATIO`` of the configured max.
        """

        if context_window is not None and estimated_token_count is not None:
            soft_ratio = self._get_compaction_soft_ratio()
            if soft_ratio is not None:
                soft_threshold = context_window * soft_ratio
                if estimated_token_count >= soft_threshold:
                    logger.info(
                        "Compaction triggered by soft context-window threshold: input_tokens=%s soft_threshold=%s context_window=%s ratio=%s",
                        estimated_token_count,
                        soft_threshold,
                        context_window,
                        soft_ratio,
                    )
                    return True

            reserved_output_tokens = output_window or 0
            context_tokens = estimated_token_count + reserved_output_tokens
            if context_tokens >= context_window:
                logger.info(
                    "Compaction triggered by hard context-window pressure: input_tokens=%s reserved_output_tokens=%s context_tokens=%s context_window=%s",
                    estimated_token_count,
                    reserved_output_tokens,
                    context_tokens,
                    context_window,
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

        return False

    def _get_compaction_soft_ratio(self) -> float | None:
        """Return the soft-trigger ratio when configured to ``(0, 1)``, else None.

        Returns None when the config service doesn't expose the accessor or
        when the configured value is outside ``(0, 1)`` — disabling the soft
        branch and falling back to the hard context-window check.
        """

        getter = getattr(self._config_service, "get_compaction_soft_ratio", None)
        if not callable(getter):
            return None
        value = getter()
        if not isinstance(value, (int, float)):
            return None
        if not (0 < value < 1):
            return None
        return float(value)

    def compact(self, summary_text: str) -> None:
        """Compact history into a summary plus the newest messages.

        Replaces older history with a system summary followed by the most
        recent conversational units preserved by the boundary tracker. The
        number of preserved units is read from the configured
        ``SummarizationSettings.preserve_units``.

        Args:
            summary_text: Summary message to insert at the start of history.
        """

        preserve_units = self._get_compaction_preserve_units()
        recent_messages = self._conversation_boundary_tracker.preserved_tail(
            self._history.snapshot(),
            preserve_units,
        )

        self._history.clear()
        self._history.append(Message(role="system", content=summary_text))
        for message in recent_messages:
            self._history.append(message)
        snapshot = self._history.snapshot()
        self._turn_budget_tracker.sync(snapshot)
        self._conversation_boundary_tracker.sync(snapshot)
        self._persist_compaction_summary(summary_text)

    def _get_compaction_preserve_units(self) -> int:
        """Return the configured preserve-unit count, defaulting to 2."""

        getter = getattr(self._config_service, "get_compaction_preserve_units", None)
        if callable(getter):
            value = getter()
            if isinstance(value, int) and value > 0:
                return value
        return 2

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
