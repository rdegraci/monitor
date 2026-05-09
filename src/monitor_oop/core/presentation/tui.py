"""Top-level TUI coordinator for the Monitor OOP presentation layer."""
from __future__ import annotations

from collections import deque
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
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
from monitor_oop.core.conversation_session import ConversationTurnResult
from monitor_oop.core.presentation.events import BackgroundCompletionEvent
from monitor_oop.core.presentation.events import ErrorEvent
from monitor_oop.core.presentation.events import InputDraftEvent
from monitor_oop.core.presentation.events import OutputEvent
from monitor_oop.core.presentation.events import StatusEvent
from monitor_oop.core.presentation.events import SubagentResultEvent
from monitor_oop.core.presentation.layout import TuiLayout
from monitor_oop.core.presentation.layout import build_layout
from monitor_oop.core.presentation.turn_coordinator import TurnCoordinator
from monitor_oop.core.presentation.turn_results import TurnCompletionResult
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
    _executor: ThreadPoolExecutor = field(init=False)
    _completion_results: Deque[TurnCompletionResult] = field(init=False)
    _pending_completion_flush: bool = field(init=False, default=False)

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
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._completion_results = deque()
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
        self._executor.shutdown(wait=False, cancel_futures=False)
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
        draft_text = self._input_area.text
        if self._is_exit_command(draft_text):
            self._input_area.text = ""
            self.stop()
            return True
        return self._submit_current_draft()

    def _is_exit_command(self, submitted_text: str) -> bool:
        """Detect exit and quit commands before background turn execution."""
        normalized_text = submitted_text.strip()
        if not normalized_text:
            return False
        return normalized_text.lower() in {"exit", "quit"}

    def _request_ui_refresh(self) -> None:
        """Request a prompt_toolkit refresh from the UI thread."""
        self._flush_pending_completions_if_needed()
        self._refresh_ui()

    def _submit_current_draft(self) -> bool:
        """Submit the current draft and refresh the presentation state."""
        draft_text = self._input_area.text
        self._input_area.text = ""
        self.status_text = "working"
        self.enqueue_event(OutputEvent(text=draft_text))
        self.enqueue_event(StatusEvent(text="working"))
        self._request_ui_refresh()
        self._run_turn_async(draft_text)
        return True

    def _run_turn_async(self, draft_text: str) -> None:
        """Process a user turn in the background and publish the completion result."""
        future = self._executor.submit(self._execute_turn, draft_text)
        future.add_done_callback(self._handle_turn_completion)

    def _execute_turn(self, input_text: str) -> TurnCompletionResult:
        """Execute a conversation turn and normalize the result."""
        task_id = self.turn_coordinator.snapshot().active_task_id
        try:
            turn_result = self._conversation_session.submit_input(input_text)
            if turn_result is None:
                return TurnCompletionResult(
                    task_id=task_id,
                    input_text=input_text,
                    assistant_text="",
                    success=False,
                    status_text="conversation turn did not produce a result",
                )
            if not isinstance(turn_result, ConversationTurnResult):
                return TurnCompletionResult(
                    task_id=task_id,
                    input_text=input_text,
                    assistant_text="",
                    success=False,
                    status_text="conversation turn returned an unexpected result",
                )
            return TurnCompletionResult(
                task_id=task_id,
                input_text=input_text,
                assistant_text=str(turn_result.assistant_text),
                success=True,
                status_text=str(turn_result.status_text),
            )
        except Exception as exc:
            return TurnCompletionResult(
                task_id=task_id,
                input_text=input_text,
                assistant_text="",
                success=False,
                status_text=str(exc),
            )

    def _build_completion_events(self, completion_result: TurnCompletionResult) -> list[object]:
        """Convert a completed turn into presentation events."""
        events: list[object] = []
        if completion_result.success:
            if completion_result.assistant_text:
                events.append(OutputEvent(text=completion_result.assistant_text))
            events.append(
                BackgroundCompletionEvent(
                    task_id=completion_result.task_id,
                    success=True,
                )
            )
        else:
            events.append(ErrorEvent(text=completion_result.status_text))
            events.append(
                BackgroundCompletionEvent(
                    task_id=completion_result.task_id,
                    success=False,
                )
            )
        events.append(StatusEvent(text="idle"))
        return events

    def _enqueue_completion_events(self, completion_result: TurnCompletionResult) -> None:
        """Convert a completed turn into queued presentation events."""
        for event in self._build_completion_events(completion_result):
            self.enqueue_event(event)

    def _request_completion_flush(self) -> None:
        """Mark that pending completion results should be applied by the UI thread."""
        self._pending_completion_flush = True

    def _enqueue_turn_completion_result(self, completion_result: TurnCompletionResult) -> None:
        """Capture a background turn result for later UI-thread processing."""
        self._completion_results.append(completion_result)
        self._request_completion_flush()
        self._request_ui_refresh()

    def drain_pending_completions(self) -> None:
        """Flush pending background completion results into presentation events."""
        while self._completion_results:
            completion_result = self._completion_results.popleft()
            self._enqueue_completion_events(completion_result)
        self._pending_completion_flush = False
        self.drain_events()

    def _flush_pending_completions_if_needed(self) -> None:
        """Apply background completion results from the UI thread when needed."""
        if not self._pending_completion_flush:
            return
        self.drain_pending_completions()

    def _handle_turn_completion(self, future: Future[TurnCompletionResult]) -> None:
        """Apply the result of a background turn to the presentation state."""
        completion_result = future.result()
        self._enqueue_turn_completion_result(completion_result)

    def _refresh_ui(self) -> None:
        """Synchronize prompt_toolkit widgets with the current state."""
        self._flush_pending_completions_if_needed()
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
        if isinstance(event, ErrorEvent):
            self.turn_coordinator.add_background_event(event)
            self.output_buffer.append(event.text)
            self.status_text = "error"
            self.sync_active_task_id()
            return
        if isinstance(event, SubagentResultEvent):
            self.turn_coordinator.add_subagent_result(event)
            self.output_buffer.append(event.text)
            self.sync_active_task_id()
            return
        if isinstance(event, InputDraftEvent):
            self.input_draft = event.draft_text
            self._input_area.text = event.draft_text
            return
