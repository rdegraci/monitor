"""Tests for TUI events."""
from __future__ import annotations

from monitor_oop.core.presentation.events import BackgroundCompletionEvent
from monitor_oop.core.presentation.events import BaseEvent
from monitor_oop.core.presentation.events import ErrorEvent
from monitor_oop.core.presentation.events import InputDraftEvent
from monitor_oop.core.presentation.events import OutputEvent
from monitor_oop.core.presentation.events import StatusEvent
from monitor_oop.core.presentation.events import SubagentResultEvent


def test_base_event_populates_defaults() -> None:
    """Verify the base event populates metadata defaults."""

    event = BaseEvent()

    assert event.id
    assert event.source == "monitor_oop"
    assert event.timestamp is not None


def test_output_event_populates_kind_and_text() -> None:
    """Verify output events carry visible text."""

    event = OutputEvent(text="hello")

    assert event.kind == "output"
    assert event.text == "hello"


def test_status_event_populates_kind_and_text() -> None:
    """Verify status events carry concise status text."""

    event = StatusEvent(text="running")

    assert event.kind == "status"
    assert event.text == "running"


def test_background_completion_event_populates_task_fields() -> None:
    """Verify background completion events carry task information."""

    event = BackgroundCompletionEvent(task_id="task-1", success=False, exit_code=3)

    assert event.kind == "background_completion"
    assert event.task_id == "task-1"
    assert event.success is False
    assert event.exit_code == 3


def test_subagent_result_event_populates_metadata_defaults() -> None:
    """Verify subagent result events carry payload and metadata."""

    event = SubagentResultEvent(task_id="task-2", text="result")

    assert event.kind == "subagent_result"
    assert event.task_id == "task-2"
    assert event.text == "result"
    assert event.metadata == {}


def test_error_event_populates_details_defaults() -> None:
    """Verify error events carry details without extra setup."""

    event = ErrorEvent(text="boom")

    assert event.kind == "error"
    assert event.text == "boom"
    assert event.details == {}


def test_input_draft_event_populates_draft_text() -> None:
    """Verify input draft events carry the current draft."""

    event = InputDraftEvent(draft_text="partial")

    assert event.kind == "input_draft"
    assert event.draft_text == "partial"
