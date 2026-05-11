"""Event types for the Monitor OOP TUI and subagent flow."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4


@dataclass(slots=True)
class BaseEvent:
    """Base event metadata shared by TUI and subagent events."""

    id: str = field(default_factory=lambda: str(uuid4()))
    source: str = "monitor_oop"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class TranscriptEvent(BaseEvent):
    """Transcript entry intended for the presentation layer."""

    role: Literal["user", "assistant", "error", "subagent"] = "assistant"
    text: str = ""


@dataclass(slots=True)
class UserTranscriptEvent(TranscriptEvent):
    """Transcript entry containing a user message."""

    role: Literal["user"] = "user"


@dataclass(slots=True)
class AssistantTranscriptEvent(TranscriptEvent):
    """Transcript entry containing an assistant message."""

    role: Literal["assistant"] = "assistant"


@dataclass(slots=True)
class ErrorTranscriptEvent(TranscriptEvent):
    """Transcript entry containing an error message."""

    role: Literal["error"] = "error"


@dataclass(slots=True)
class SubagentTranscriptEvent(TranscriptEvent):
    """Transcript entry containing a subagent message."""

    role: Literal["subagent"] = "subagent"


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
