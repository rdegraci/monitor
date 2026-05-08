"""Top-level TUI coordinator for the Monitor OOP presentation layer."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Dimension
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea

from monitor_oop.core.conversation_session import ConversationSession
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
    _conversation_session: ConversationSession = field(init=False)
    _application: Application | None = field(init=False, default=None)
    _output_area: TextArea = field(init=False)
    _status_control: FormattedTextControl = field(init=False)
    _input_area: TextArea = field(init=False)

    def __post_init__(self) -> None:
        """Build the prompt_toolkit application shell."""
        self._conversation_session = ConversationSession(self.runtime_context)
        self._status_control = FormattedTextControl(text=self._get_status_text)
        self._output_area = TextArea(
            text="",
            read_only=True,
            scrollbar=True,
            wrap_lines=True,
            height=Dimension(min=8, weight=1),
            focusable=False,
        )
        self._input_area = TextArea(
            text="",
            multiline=True,
            focus_on_click=True,
            height=Dimension(min=3, max=3),
        )
        self._input_area.buffer.accept_handler = self._submit_input
        self._application = Application(
            layout=Layout(self._build_ui(), focused_element=self._input_area),
            key_bindings=self._build_key_bindings(),
            full_screen=True,
        )

    def start(self) -> None:
        """Start the TUI loop."""
        self.is_running = True
        self.turn_coordinator.begin_turn()
        self.sync_active_task_id()

    def run(self) -> None:
        """Run the prompt_toolkit application."""
        self.start()
        assert self._application is not None
        self._application.run()

    def stop(self) -> None:
        """Stop the TUI loop."""
        self.is_running = False
        if self._application is not None and getattr(self._application, "is_running", False):
            self._application.exit()

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
        self._refresh_ui()

    def sync_active_task_id(self) -> None:
        """Mirror the coordinator's active task into the TUI state."""
        snapshot = self.turn_coordinator.snapshot()
        self.active_task_id = snapshot.active_task_id

    def _build_ui(self) -> HSplit:
        """Build the prompt_toolkit container tree."""
        return HSplit(
            [
                Window(
                    content=FormattedTextControl(text=self.layout.output_title),
                    height=1,
                    dont_extend_height=True,
                ),
                self._output_area,
                Window(
                    content=FormattedTextControl(text=self.layout.status_title),
                    height=1,
                    dont_extend_height=True,
                ),
                Window(
                    content=self._status_control,
                    height=1,
                    dont_extend_height=True,
                ),
                Window(
                    content=FormattedTextControl(text=self.layout.input_title),
                    height=1,
                    dont_extend_height=True,
                ),
                self._input_area,
            ]
        )

    def _build_key_bindings(self) -> KeyBindings:
        """Bind keys for basic application control."""
        key_bindings = KeyBindings()

        @key_bindings.add("c-c")
        @key_bindings.add("escape")
        def _exit() -> None:
            self.stop()

        @key_bindings.add("enter")
        def _submit(event: object) -> None:
            self._submit_input(event)

        return key_bindings

    def _submit_input(self, event: object | None = None) -> bool:
        """Submit the current draft into the conversation flow."""
        return self._submit_current_draft()

    def _submit_current_draft(self) -> bool:
        """Submit the current draft and refresh the presentation state."""
        draft_text = self._input_area.text
        result = self._conversation_session.submit_input(draft_text)
        if result is None:
            self.stop()
            return True
        if draft_text:
            self.output_buffer.append(draft_text)
        self.output_buffer.append(result.assistant_text)
        self.status_text = result.status_text
        self.input_draft = ""
        self._input_area.text = ""
        self.drain_events()
        self._refresh_ui()
        return True

    def _refresh_ui(self) -> None:
        """Synchronize prompt_toolkit widgets with the current state."""
        self._output_area.text = "\n".join(self.output_buffer)
        assert self._application is not None
        self._application.invalidate()

    def _get_status_text(self) -> str:
        """Return the rendered status line."""
        return self.status_text

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
            self._input_area.text = event.draft_text
            return
