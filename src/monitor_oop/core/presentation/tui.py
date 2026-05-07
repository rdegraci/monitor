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

    def stop(self) -> None:
        """Stop the TUI loop."""

        self.is_running = False

    def enqueue_event(self, event: object) -> None:
        """Add an event to the internal queue."""

        self.event_queue.append(event)

    def drain_events(self) -> None:
        """Drain queued events into the local presentation buffers."""

        while self.event_queue:
            event = self.event_queue.popleft()
            self._handle_event(event)

    def _handle_event(self, event: object) -> None:
        """Handle a single presentation event."""

        if isinstance(event, OutputEvent):
            self.output_buffer.append(event.text)
            return
        if isinstance(event, StatusEvent):
            self.status_text = event.text
            return
        if isinstance(event, BackgroundCompletionEvent):
            self.status_text = "completed" if event.success else "failed"
            return
        if isinstance(event, SubagentResultEvent):
            self.output_buffer.append(event.text)
            return
        if isinstance(event, ErrorEvent):
            self.output_buffer.append(event.text)
            self.status_text = "error"
            return
        if isinstance(event, InputDraftEvent):
            self.input_draft = event.draft_text
            return
