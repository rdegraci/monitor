"""Tests for TuiApp transcript plumbing."""
from __future__ import annotations

from dataclasses import dataclass

from monitor_oop.core.presentation.events import AssistantTranscriptEvent
from monitor_oop.core.presentation.events import ErrorTranscriptEvent
from monitor_oop.core.presentation.events import SubagentTranscriptEvent
from monitor_oop.core.presentation.events import UserTranscriptEvent
from monitor_oop.core.presentation.transcript_buffer import TranscriptBuffer
from monitor_oop.core.presentation.transcript_renderer import TranscriptRenderer
from monitor_oop.core.presentation.transcript_viewport import TranscriptViewport
from monitor_oop.core.presentation.tui import TuiApp


@dataclass(slots=True)
class _StubSnapshot:
    """Stub coordinator snapshot for TuiApp tests."""

    active_task_id: str = "task-1"


class _StubTurnCoordinator:
    """Stub turn coordinator for TuiApp tests."""

    def __init__(self) -> None:
        self.background_events: list[object] = []
        self.subagent_results: list[object] = []
        self.completed_events: list[object] = []

    def begin_turn(self) -> None:
        """Begin a turn."""

    def snapshot(self) -> _StubSnapshot:
        """Return a stub snapshot."""
        return _StubSnapshot()

    def mark_background_complete(self, event: object) -> None:
        """Record a completed background event."""
        self.completed_events.append(event)

    def add_background_event(self, event: object) -> None:
        """Record a background event."""
        self.background_events.append(event)

    def add_subagent_result(self, event: object) -> None:
        """Record a subagent result."""
        self.subagent_results.append(event)


class _StubConversationSession:
    """Stub conversation session for TuiApp tests."""

    def submit_input(self, text: str) -> object:
        """Return a deterministic assistant response."""
        return type(
            "ConversationTurnResult",
            (),
            {"assistant_text": f"assistant: {text}", "status_text": "idle"},
        )()


class _StubBuffer:
    """Stub text buffer for TuiApp tests."""

    def __init__(self) -> None:
        self.text = ""


class _StubOutputArea:
    """Stub output area for TuiApp tests."""

    def __init__(self) -> None:
        self.text = ""
        self.buffer = _StubBuffer()


class _StubInputArea:
    """Stub input area for TuiApp tests."""

    def __init__(self) -> None:
        self.text = ""
        self.buffer = _StubBuffer()


class _StubExecutor:
    """Stub executor for TuiApp tests."""

    def submit(self, fn, *args) -> None:
        """Ignore submitted work."""

    def shutdown(self, **kwargs) -> None:
        """Ignore shutdown requests."""


class _StubCompletionQueue:
    """Stub completion queue for TuiApp tests."""

    needs_flush = False

    def request_flush(self) -> None:
        """Ignore flush requests."""

    def enqueue(self, result: object) -> None:
        """Ignore enqueued results."""

    def __bool__(self) -> bool:
        return False

    def popleft(self) -> object:
        """Return a placeholder result."""
        return None

    def clear_flush_request(self) -> None:
        """Ignore flush state changes."""


class _StubApplication:
    """Stub application for TuiApp tests."""

    is_running = False

    def invalidate(self) -> None:
        """Ignore invalidation requests."""

    def exit(self) -> None:
        """Ignore exit requests."""


class _TestableTuiApp(TuiApp):
    """Test-friendly TuiApp without starting prompt_toolkit."""

    def __post_init__(self) -> None:
        """Initialize the app with test doubles."""
        self._conversation_session = _StubConversationSession()
        self._status_control = None
        self._transcript_buffer = TranscriptBuffer()
        self._transcript_renderer = TranscriptRenderer()
        self._transcript_viewport = TranscriptViewport(
            buffer=self._transcript_buffer,
            renderer=self._transcript_renderer,
        )
        self._output_area = _StubOutputArea()
        self._input_area = _StubInputArea()
        self._executor = _StubExecutor()
        self._completion_queue = _StubCompletionQueue()
        self._application = _StubApplication()


def test_handle_event_appends_transcript_entries() -> None:
    """Transcript events should update the buffer and visible transcript."""
    app = _TestableTuiApp(runtime_context=object(), turn_coordinator=_StubTurnCoordinator())

    app._handle_event(UserTranscriptEvent(text="hello"))
    app._handle_event(AssistantTranscriptEvent(text="world"))
    app._handle_event(ErrorTranscriptEvent(text="oops"))
    app._handle_event(SubagentTranscriptEvent(text="sub"))

    assert app._transcript_buffer.entries[0].text == "hello"
    assert app._transcript_buffer.entries[1].text == "world"
    assert app._transcript_buffer.entries[2].text == "oops"
    assert app._transcript_buffer.entries[3].text == "sub"
    assert app._transcript_viewport.visible_text() == "> hello\nSTX\nworld\n\nETX\nERROR: oops\nSUBAGENT: sub"


def test_output_refresh_reflects_visible_transcript() -> None:
    """Refreshing the UI should copy visible transcript text to the output widget."""
    app = _TestableTuiApp(runtime_context=object(), turn_coordinator=_StubTurnCoordinator())

    app._handle_event(UserTranscriptEvent(text="first"))
    app._handle_event(UserTranscriptEvent(text="second"))
    app._refresh_ui()

    assert app._output_area.text == "> first\n> second"


def test_new_transcript_events_restore_tail_follow() -> None:
    """Appending transcript events should restore tail follow."""
    app = _TestableTuiApp(runtime_context=object(), turn_coordinator=_StubTurnCoordinator())

    app._handle_event(UserTranscriptEvent(text="one"))
    assert app._transcript_viewport.follow_tail is True

    app._transcript_viewport.scroll_up(viewport_size=1)
    assert app._transcript_viewport.follow_tail is True

    app._handle_event(UserTranscriptEvent(text="two"))
    assert app._transcript_viewport.follow_tail is True
    assert app._transcript_viewport.visible_text() == "> one\n> two"


def test_background_completion_updates_status_and_task_id() -> None:
    """Background completion events should update status and task state."""
    coordinator = _StubTurnCoordinator()
    app = _TestableTuiApp(runtime_context=object(), turn_coordinator=coordinator)
    event = type("BackgroundCompletionEvent", (), {"task_id": "task-1", "success": True})()

    app._enqueue_turn_completion_result(event)

    assert app._completion_queue is not None
    assert app._completion_queue.needs_flush is False
    assert app.status_text == "idle"
    assert coordinator.completed_events == []
