"""Completion queue helpers for the Monitor OOP TUI."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from monitor_oop.core.presentation.turn_results import TurnCompletionResult


@dataclass(slots=True)
class CompletionQueue:
    """Buffer background completion results until the UI thread flushes them."""

    results: Deque[TurnCompletionResult] = field(default_factory=deque)
    _needs_flush: bool = False

    def __bool__(self) -> bool:
        """Return whether any completion results are queued."""
        return bool(self.results)

    @property
    def needs_flush(self) -> bool:
        """Return whether completion results are waiting to be applied."""
        return self._needs_flush

    def request_flush(self) -> None:
        """Mark the queue as needing a UI-thread flush."""
        self._needs_flush = True

    def clear_flush_request(self) -> None:
        """Clear the pending flush request without touching queued results."""
        self._needs_flush = False

    def enqueue(self, completion_result: TurnCompletionResult) -> None:
        """Store a completion result for later UI-thread processing."""
        self.results.append(completion_result)
        self.request_flush()

    def popleft(self) -> TurnCompletionResult:
        """Remove and return the next queued completion result."""
        return self.results.popleft()
