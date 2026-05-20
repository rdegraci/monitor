"""Tests for the TUI coordinator."""
from collections import deque
from unittest.mock import MagicMock

from monitor_oop.core.command_processor import CommandProcessor
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.infrastructure.macro_expander import MacroExpander
from monitor_oop.core.infrastructure.macro_store import MacroStore
from monitor_oop.core.infrastructure.prompt_store import PromptStore
from monitor_oop.core.llm_service import LLMService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.presentation.events import AssistantTranscriptEvent
from monitor_oop.core.presentation.events import ErrorEvent
from monitor_oop.core.presentation.events import InputDraftEvent
from monitor_oop.core.presentation.events import StatusEvent
from monitor_oop.core.presentation.events import SubagentResultEvent
from monitor_oop.core.presentation.layout import build_layout
from monitor_oop.core.presentation.turn_coordinator import TurnCoordinator
from monitor_oop.core.presentation.tui import TuiApp
from monitor_oop.core.prompt_service import PromptService
from monitor_oop.core.runtime_context import RuntimeContext
from monitor_oop.core.status_service import StatusService
from monitor_oop.core.summarization_service import SummarizationService


def build_runtime_context() -> RuntimeContext:
    """Build a minimal runtime context for TUI tests."""

    config_service = ConfigService()
    history_service = HistoryService(config_service)
    macro_store = MacroStore("monitor_oop")
    macro_expander = MacroExpander("{{", "}}")
    macro_service = MacroService(config_service, macro_store, macro_expander)
    prompt_store = PromptStore(config_service)
    prompt_service = PromptService(config_service, prompt_store)
    status_service = StatusService()

    class RequestBuilderStub:
        def build_input(self, *args, **kwargs):
            return []

    class ResponseClientStub:
        def create_response(self, *args, **kwargs):
            return object()

    class ToolCallHandlerStub:
        def execute_tool_calls(self, *args, **kwargs):
            return [], False

    class AdapterStub:
        def extract_text(self, response):
            return ""

    class ToolServiceStub:
        def build_responses_tools(self):
            return []

    class CompactionStoreStub:
        def __init__(self, *args, **kwargs):
            pass

    request_builder_stub = RequestBuilderStub()
    response_client_stub = ResponseClientStub()
    adapter_stub = AdapterStub()
    summarization_service = SummarizationService(
        config_service=config_service,
        request_builder=request_builder_stub,
        response_client=response_client_stub,
        response_adapter=adapter_stub,
    )
    llm_service = LLMService(
        config_service=config_service,
        request_builder=request_builder_stub,
        response_client=response_client_stub,
        tool_call_handler=ToolCallHandlerStub(),
        adapter=adapter_stub,
        tool_service=ToolServiceStub(),
        prompt_service=prompt_service,
    )
    command_processor = CommandProcessor(
        config_service, history_service, macro_service, status_service
    )
    tool_service = ToolServiceStub()
    tool_registry = object()
    compaction_store = CompactionStoreStub()
    request_capacity_service = MagicMock()
    rate_limit_service = MagicMock()

    return RuntimeContext(
        config_service=config_service,
        history_service=history_service,
        llm_service=llm_service,
        macro_service=macro_service,
        status_service=status_service,
        prompt_service=prompt_service,
        summarization_service=summarization_service,
        command_processor=command_processor,
        tool_service=tool_service,
        tool_registry=tool_registry,
        compaction_store=compaction_store,
        request_capacity_service=request_capacity_service,
        rate_limit_service=rate_limit_service,
    )


def test_tui_app_starts_and_handles_basic_events() -> None:
    """Verify the TUI app starts and updates publicly observable state."""

    runtime_context = build_runtime_context()
    turn_coordinator = TurnCoordinator()
    tui = TuiApp(
        runtime_context=runtime_context,
        turn_coordinator=turn_coordinator,
        layout=build_layout(),
        event_queue=deque(),
    )

    tui.start()
    tui.enqueue_event(StatusEvent(text="running"))
    tui.enqueue_event(
        AssistantTranscriptEvent(
            text="assistant response",
        )
    )
    tui.enqueue_event(
        SubagentResultEvent(task_id="task-1", text="subagent result")
    )
    tui.enqueue_event(ErrorEvent(text="boom"))
    tui.enqueue_event(InputDraftEvent(draft_text="draft"))
    tui.drain_events()

    assert tui.is_running is True
    assert tui.input_draft == "draft"
    assert tui.status_text in {"running", "error"}
    snapshot = turn_coordinator.snapshot()
    assert any(
        entry.text == "subagent result" and entry.kind == "subagent_result"
        for entry in snapshot.internal_context_entries
    )
    assert snapshot.error_state is not None
    assert snapshot.error_state.text == "boom"


def test_tui_app_stop_clears_running_state() -> None:
    """Verify stopping the TUI clears the running flag."""

    runtime_context = build_runtime_context()
    turn_coordinator = TurnCoordinator()
    tui = TuiApp(
        runtime_context=runtime_context,
        turn_coordinator=turn_coordinator,
        layout=build_layout(),
        event_queue=deque(),
    )

    tui.start()
    tui.stop()

    assert tui.is_running is False


def test_tui_app_runtime_context_status_listener_updates_status_text() -> None:
    """Emitting a phase status through the runtime context should flip the TUI status.

    Exercises the public wiring (``runtime_context.emit_status``) rather than
    naming the private callback the TUI installs.
    """

    runtime_context = build_runtime_context()
    turn_coordinator = TurnCoordinator()
    tui = TuiApp(
        runtime_context=runtime_context,
        turn_coordinator=turn_coordinator,
        layout=build_layout(),
        event_queue=deque(),
    )

    runtime_context.emit_status("compacting")
    assert tui.status_text == "compacting"

    runtime_context.emit_status("working")
    assert tui.status_text == "working"

    runtime_context.emit_status("idle")
    assert tui.status_text == "idle"


def test_tui_app_completion_event_sets_compound_idle_status() -> None:
    """Verify a successful turn ends on 'completed (idle)'."""

    from monitor_oop.core.presentation.events import BackgroundCompletionEvent

    runtime_context = build_runtime_context()
    turn_coordinator = TurnCoordinator()
    tui = TuiApp(
        runtime_context=runtime_context,
        turn_coordinator=turn_coordinator,
        layout=build_layout(),
        event_queue=deque(),
    )

    tui.start()
    tui.enqueue_event(BackgroundCompletionEvent(task_id="t1", success=True))
    tui.drain_events()

    assert tui.status_text == "completed (idle)"


def test_tui_app_failed_completion_event_sets_failed_idle_status() -> None:
    """Verify a failed turn ends on 'failed (idle)'."""

    from monitor_oop.core.presentation.events import BackgroundCompletionEvent

    runtime_context = build_runtime_context()
    turn_coordinator = TurnCoordinator()
    tui = TuiApp(
        runtime_context=runtime_context,
        turn_coordinator=turn_coordinator,
        layout=build_layout(),
        event_queue=deque(),
    )

    tui.start()
    tui.enqueue_event(BackgroundCompletionEvent(task_id="t1", success=False))
    tui.drain_events()

    assert tui.status_text == "failed (idle)"


def test_tui_app_rate_limited_completion_event_sets_transient_status() -> None:
    """A rate-limit denial should produce a distinct 'rate limited (idle)' status."""

    from monitor_oop.core.presentation.events import BackgroundCompletionEvent

    runtime_context = build_runtime_context()
    turn_coordinator = TurnCoordinator()
    tui = TuiApp(
        runtime_context=runtime_context,
        turn_coordinator=turn_coordinator,
        layout=build_layout(),
        event_queue=deque(),
    )

    tui.start()
    tui.enqueue_event(
        BackgroundCompletionEvent(
            task_id="t1", success=False, failure_kind="rate_limited"
        )
    )
    tui.drain_events()

    assert tui.status_text == "rate limited (idle)"
