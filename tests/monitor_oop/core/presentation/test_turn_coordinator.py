"""Tests for TurnCoordinator."""
from __future__ import annotations

from monitor_oop.core.presentation.events import BackgroundCompletionEvent
from monitor_oop.core.presentation.events import ErrorEvent
from monitor_oop.core.presentation.events import OutputEvent
from monitor_oop.core.presentation.events import SubagentResultEvent
from monitor_oop.core.presentation.turn_coordinator import InternalContextEntry
from monitor_oop.core.presentation.turn_coordinator import TurnCoordinator


def test_begin_turn_clears_stale_state() -> None:
    """Verify a new turn starts from a clean state."""

    coordinator = TurnCoordinator()
    coordinator.add_internal_context(InternalContextEntry(text="old"))
    coordinator.add_background_event(OutputEvent(text="old event"))

    coordinator.begin_turn()
    snapshot = coordinator.snapshot()

    assert snapshot.turn_id
    assert snapshot.active_task_id is None
    assert snapshot.background_status == "idle"
    assert snapshot.has_pending_work is False
    assert snapshot.internal_context_entries == []
    assert snapshot.subagent_results == []
    assert snapshot.background_events == []
    assert snapshot.request_context_ready is False


def test_begin_background_work_sets_active_task_and_running_status() -> None:
    """Verify beginning background work updates task and status state."""

    coordinator = TurnCoordinator()
    coordinator.begin_turn()

    coordinator.begin_background_work(task_id="task-1")
    snapshot = coordinator.snapshot()

    assert snapshot.active_task_id == "task-1"
    assert snapshot.has_pending_work is True
    assert snapshot.background_status == "running"


def test_add_internal_context_appends_in_order() -> None:
    """Verify internal context entries are appended in order."""

    coordinator = TurnCoordinator()
    coordinator.begin_turn()
    first = InternalContextEntry(text="one")
    second = InternalContextEntry(text="two")

    coordinator.add_internal_context(first)
    coordinator.add_internal_context(second)
    snapshot = coordinator.snapshot()

    assert snapshot.internal_context_entries == [first, second]
    assert snapshot.request_context_ready is True


def test_add_subagent_result_mirrors_into_internal_context() -> None:
    """Verify subagent results are stored as semantic and generic context."""

    coordinator = TurnCoordinator()
    coordinator.begin_turn()
    result = SubagentResultEvent(task_id="task-1", text="subagent output")

    coordinator.add_subagent_result(result)
    snapshot = coordinator.snapshot()

    assert snapshot.subagent_results == [result]
    assert len(snapshot.internal_context_entries) == 1
    assert snapshot.internal_context_entries[0].text == "subagent output"
    assert snapshot.internal_context_entries[0].kind == "subagent_result"


def test_add_background_event_stores_completion_event_once_and_updates_status() -> None:
    """Verify completion events are stored once and update background status."""

    coordinator = TurnCoordinator()
    coordinator.begin_turn()
    coordinator.set_pending_work(True)
    event = BackgroundCompletionEvent(task_id="task-1", success=True, exit_code=0)

    coordinator.add_background_event(event)
    snapshot = coordinator.snapshot()

    assert len(snapshot.background_events) == 1
    assert snapshot.background_events[0].task_id == event.task_id
    assert snapshot.background_events[0].success == event.success
    assert snapshot.background_events[0].exit_code == event.exit_code
    assert snapshot.background_status == "completed"
    assert snapshot.has_pending_work is False


def test_add_background_event_updates_status_and_pending_state() -> None:
    """Verify completion events update background status."""

    coordinator = TurnCoordinator()
    coordinator.begin_turn()
    coordinator.set_pending_work(True)
    event = BackgroundCompletionEvent(task_id="task-1", success=True, exit_code=0)

    coordinator.add_background_event(event)
    snapshot = coordinator.snapshot()

    assert snapshot.background_events[-1].task_id == event.task_id
    assert snapshot.background_events[-1].success == event.success
    assert snapshot.background_events[-1].exit_code == event.exit_code
    assert snapshot.background_status == "completed"
    assert snapshot.has_pending_work is False


def test_add_error_event_marks_error_state() -> None:
    """Verify error events update error state and status."""

    coordinator = TurnCoordinator()
    coordinator.begin_turn()
    event = ErrorEvent(text="boom")

    coordinator.add_background_event(event)
    snapshot = coordinator.snapshot()

    assert snapshot.background_events[-1] == event
    assert snapshot.background_status == "error"
    assert snapshot.error_state == event


def test_mark_background_complete_sets_failed_status() -> None:
    """Verify failed completions are reflected in status."""

    coordinator = TurnCoordinator()
    coordinator.begin_turn()
    coordinator.set_pending_work(True)

    coordinator.mark_background_complete(task_id="task-1", success=False, exit_code=7)
    snapshot = coordinator.snapshot()

    assert snapshot.background_status == "failed:7"
    assert snapshot.has_pending_work is False
    assert len(snapshot.background_events) == 1
    assert snapshot.background_events[0].task_id == "task-1"
    assert snapshot.background_events[0].success is False
    assert snapshot.background_events[0].exit_code == 7


def test_clear_turn_removes_turn_scoped_state() -> None:
    """Verify turn-local state is removed when clearing the turn."""

    coordinator = TurnCoordinator()
    coordinator.begin_turn()
    coordinator.add_internal_context(InternalContextEntry(text="one"))
    coordinator.add_subagent_result(SubagentResultEvent(task_id="task-1", text="two"))
    coordinator.add_background_event(OutputEvent(text="event"))
    coordinator.set_pending_work(True)

    coordinator.clear_turn()
    snapshot = coordinator.snapshot()

    assert snapshot.active_task_id is None
    assert snapshot.internal_context_entries == []
    assert snapshot.subagent_results == []
    assert snapshot.background_events == []
    assert snapshot.background_status == "idle"
    assert snapshot.has_pending_work is False
    assert snapshot.request_context_ready is False
