"""Top-level TUI coordinator for the Monitor OOP presentation layer."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from monitor_oop.core.presentation.events import BackgroundCompletionEvent
from monitor_oop.core.presentation.events import ErrorEvent
from monitor_oop.core.presentation.events import InputDraftEvent
from monitor_oop.core.presentation.events import OutputEvent
from monitor_oop.core.presentation.events import StatusEvent
from monitor_oop.core.presentation.events import SubagentResultEvent
from monitor_oop.core.presentation.layout import TuiLayout
from monitor_oop.core.presentation.layout import build_layout
from monitor_oop.core.presentation.turn_coordinator import TurnCoordinator
from monitor_oop.core.runtime_context import RuntimeContext


@dataclass(slots=True)
class TuiApp:
    """Own the lightweight TUI lifecycle and event flow."""

    runtime_context: RuntimeContext
    turn_coordinator: TurnCoordinator
    layout: TuiLayout = field(default_factory=build_layout)
    event_queue: Deque[object] = field(default_factory=deque)
    is_running: bool = False
    output_buffer: list[str] = field(default_factory=list)
    status_text: str = "idle"
    input_draft: str = ""
    active_task_id: str = ""

    def start(self) -> None:
        """Start the TUI loop."""

        self.is_running = True
        self.turn_coordinator.begin_turn()
        self.sync_active_task_id()

    def stop(self) -> None:
        """Stop the TUI loop."""

        self.is_running = False

    def enqueue_event(self, event: object) -> None:
        """Add an event to the internal queue."""

        self.event_queue.append(event)

    def enqueue_input_draft_event(self, draft_text: str) -> None:
        """Enqueue an input draft event."""

        self.enqueue_event(InputDraftEvent(draft_text=draft_text))

    def drain_events(self) -> None:
        """Drain queued events into the local presentation buffers."""

        while self.event_queue:
            event = self.event_queue.popleft()
            self._handle_event(event)

    def sync_active_task_id(self) -> None:
        """Mirror the coordinator's active task into the TUI state."""

        snapshot = self.turn_coordinator.snapshot()
        self.active_task_id = snapshot.active_task_id

    def render(self) -> str:
        """Render a simple three-region textual view."""

        return self._build_rendered_view()

    def _build_rendered_view(self) -> str:
        """Build the textual view for the current TUI state."""

        output_text = "\n".join(self.output_buffer)
        return (
            f"{self.layout.output_title}\n"
            f"{output_text}\n\n"
            f"{self.layout.status_title}\n"
            f"{self.status_text}\n\n"
            f"{self.layout.input_title}\n"
            f"{self.input_draft}"
        )

    def _handle_event(self, event: object) -> None:
        """Handle a single presentation event."""

        if isinstance(event, OutputEvent):
            self.output_buffer.append(event.text)
            return
        if isinstance(event, StatusEvent):
            self.status_text = event.text
            return
        if isinstance(event, BackgroundCompletionEvent):
            self.turn_coordinator.mark_background_complete(event)
            self.status_text = "completed" if event.success else "failed"
            self.sync_active_task_id()
            return
        if isinstance(event, SubagentResultEvent):
            self.turn_coordinator.add_subagent_result(event)
            self.output_buffer.append(event.text)
            self.sync_active_task_id()
            return
        if isinstance(event, ErrorEvent):
            self.turn_coordinator.add_background_event(event)
            self.output_buffer.append(event.text)
            self.status_text = "error"
            self.sync_active_task_id()
            return
        if isinstance(event, InputDraftEvent):
            self.input_draft = event.draft_text
            return
