"""Event types for the Monitor OOP TUI and subagent flow."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class BaseEvent:
    """Base event metadata shared by TUI and subagent events."""

    id: str = field(default_factory=lambda: str(uuid4()))
    source: str = "monitor_oop"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class OutputEvent(BaseEvent):
    """Visible output destined for the Output pane."""

    kind: str = "output"
    text: str = ""


@dataclass(slots=True)
class StatusEvent(BaseEvent):
    """Short status update destined for the Status Line."""

    kind: str = "status"
    text: str = ""


@dataclass(slots=True)
class BackgroundCompletionEvent(BaseEvent):
    """Event emitted when background work completes."""

    kind: str = "background_completion"
    task_id: str = ""
    success: bool = True
    exit_code: int | None = None


@dataclass(slots=True)
class SubagentResultEvent(BaseEvent):
    """Event carrying a subagent result payload."""

    kind: str = "subagent_result"
    task_id: str = ""
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ErrorEvent(BaseEvent):
    """Event carrying an error message for the UI."""

    kind: str = "error"
    text: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InputDraftEvent(BaseEvent):
    """Optional event representing a live input draft."""

    kind: str = "input_draft"
    draft_text: str = ""
