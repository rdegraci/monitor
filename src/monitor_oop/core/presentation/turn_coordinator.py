"""Turn coordination for the Monitor OOP TUI and subagent flow."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from monitor_oop.core.presentation.events import BackgroundCompletionEvent
from monitor_oop.core.presentation.events import BaseEvent
from monitor_oop.core.presentation.events import ErrorEvent
from monitor_oop.core.presentation.events import SubagentResultEvent


@dataclass(slots=True)
class InternalContextEntry:
    """Structured internal context entry for a single turn."""

    id: str = field(default_factory=lambda: str(uuid4()))
    source: str = "monitor_oop"
    kind: str = "context"
    text: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TurnSnapshot:
    """Read-only view of the current turn state."""

    turn_id: str
    background_status: str
    has_pending_work: bool
    active_task_id: str | None = None
    internal_context_entries: list[InternalContextEntry] = field(default_factory=list)
    subagent_results: list[SubagentResultEvent] = field(default_factory=list)
    background_events: list[BaseEvent] = field(default_factory=list)
    request_context_ready: bool = False
    error_state: ErrorEvent | None = None
    last_event_time: datetime | None = None


class TurnCoordinator:
    """Own transient per-turn state and request context assembly inputs."""

    def __init__(self) -> None:
        self._turn_id = ""
        self._active_task_id: str | None = None
        self._internal_context_entries: list[InternalContextEntry] = []
        self._subagent_results: list[SubagentResultEvent] = []
        self._background_events: list[BaseEvent] = []
        self._background_status = "idle"
        self._has_pending_work = False
        self._request_context_ready = False
        self._error_state: ErrorEvent | None = None
        self._last_event_time: datetime | None = None

    @property
    def active_task_id(self) -> str | None:
        return self._active_task_id

    def begin_turn(self) -> None:
        """Start a fresh turn and clear stale turn-scoped data."""

        self._turn_id = str(uuid4())
        self._active_task_id = None
        self._internal_context_entries.clear()
        self._subagent_results.clear()
        self._background_events.clear()
        self._background_status = "idle"
        self._has_pending_work = False
        self._request_context_ready = False
        self._error_state = None
        self._last_event_time = datetime.now(timezone.utc)

    def set_pending_work(self, is_pending: bool) -> None:
        """Set whether the current turn has background work in progress."""

        self._has_pending_work = is_pending

    def begin_background_work(self, task_id: str) -> None:
        """Mark a background task as active for the current turn.

        Args:
            task_id: Identifier of the background task now in progress.
        """

        self._active_task_id = task_id
        self._background_status = "running"
        self.set_pending_work(True)
        self._last_event_time = datetime.now(timezone.utc)

    def add_internal_context(self, entry: InternalContextEntry) -> None:
        """Append a structured internal context record in order."""

        self._internal_context_entries.append(entry)
        self._request_context_ready = True
        self._last_event_time = entry.timestamp

    def add_subagent_result(self, result: SubagentResultEvent) -> None:
        """Store a subagent result and mirror it into internal context."""

        self._subagent_results.append(result)
        self.add_internal_context(
            InternalContextEntry(
                source=result.source,
                kind=result.kind,
                text=result.text,
                timestamp=result.timestamp,
                metadata=dict(result.metadata),
            )
        )

    def _set_background_completion_state(
        self,
        task_id: str,
        success: bool,
        exit_code: int | None = None,
    ) -> None:
        self._active_task_id = task_id
        self.set_pending_work(False)
        self._background_status = "completed" if success else "failed"
        if exit_code is not None and not success:
            self._background_status = f"failed:{exit_code}"

    def add_background_event(self, event: BaseEvent) -> None:
        """Append a turn-scoped background lifecycle event."""

        self._background_events.append(event)
        self._last_event_time = event.timestamp
        if isinstance(event, BackgroundCompletionEvent):
            self._set_background_completion_state(
                task_id=event.task_id,
                success=event.success,
                exit_code=event.exit_code,
            )
        if isinstance(event, ErrorEvent):
            self._error_state = event
            self._background_status = "error"

    def mark_background_complete(
        self,
        task_id: str,
        success: bool = True,
        exit_code: int | None = None,
    ) -> None:
        """Record task completion and update pending-work state."""

        self._set_background_completion_state(
            task_id=task_id,
            success=success,
            exit_code=exit_code,
        )
        self._background_events.append(
            BackgroundCompletionEvent(
                task_id=task_id,
                success=success,
                exit_code=exit_code,
            )
        )
        self._last_event_time = datetime.now(timezone.utc)

    def snapshot(self) -> TurnSnapshot:
        """Return a read-only snapshot of the current turn state."""

        return TurnSnapshot(
            turn_id=self._turn_id,
            background_status=self._background_status,
            has_pending_work=self._has_pending_work,
            active_task_id=self._active_task_id,
            internal_context_entries=list(self._internal_context_entries),
            subagent_results=list(self._subagent_results),
            background_events=list(self._background_events),
            request_context_ready=self._request_context_ready,
            error_state=self._error_state,
            last_event_time=self._last_event_time,
        )

    def clear_turn(self) -> None:
        """Strictly reset turn-local state for the next turn."""

        self._active_task_id = None
        self._internal_context_entries.clear()
        self._subagent_results.clear()
        self._background_events.clear()
        self._background_status = "idle"
        self._has_pending_work = False
        self._request_context_ready = False
        self._error_state = None
        self._last_event_time = None
