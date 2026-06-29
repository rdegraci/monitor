"""Shared typing helpers for monitor.lib.history."""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable, Any


@runtime_checkable
class HistoryLogger(Protocol):
    """Subset of logging.Logger used by history helpers."""

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a debug message."""

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log an info message."""

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a warning message."""

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log an error message."""

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a critical message."""


@runtime_checkable
class HistoryConfig(Protocol):
    """Subset of monitor.config used by history helpers."""

    TOTAL_TOKEN_COUNT: int
    MAX_TOKEN_COUNT: int
    CONVERSATION_MAX_SIZE: int
    SUMMARIZATION_CONFIG: dict[str, Any]
    last_summary_time: float
    RESPONSES_API: bool
    RESPONSE_ID: str | None
    MODEL: str
    REASONING_MODEL_PREFIX: str
    AUTO_COMPACT_THRESHOLD_RATIO: float
    SESSION_COMPACTION_COUNT: int

    def effective_auto_compact_ratio(self) -> float:
        """Return the active compaction ratio."""


MessageAppender = Callable[[dict, list, Callable, Callable], None]
TokenCounter = Callable[[Any], int]
UsageUpdater = Callable[..., None]
