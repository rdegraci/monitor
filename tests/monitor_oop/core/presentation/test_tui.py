"""Tests for the TUI coordinator."""
from collections import deque

from monitor_oop.core.command_processor import CommandProcessor
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.infrastructure.macro_expander import MacroExpander
from monitor_oop.core.infrastructure.macro_store import MacroStore
from monitor_oop.core.infrastructure.prompt_store import PromptStore
from monitor_oop.core.llm_service import LLMService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.presentation.events import ErrorEvent
from monitor_oop.core.presentation.events import InputDraftEvent
from monitor_oop.core.presentation.events import OutputEvent
from monitor_oop.core.presentation.events import StatusEvent
from monitor_oop.core.presentation.events import SubagentResultEvent
from monitor_oop.core.presentation.layout import build_layout
from monitor_oop.core.presentation.turn_coordinator import TurnCoordinator
from monitor_oop.core.presentation.tui import TuiApp
from monitor_oop.core.prompt_service import PromptService
from monitor_oop.core.runtime_context import RuntimeContext
from monitor_oop.core.status_service import StatusService


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

    llm_service = LLMService(
        config_service=config_service,
        request_builder=RequestBuilderStub(),
        response_client=ResponseClientStub(),
        tool_call_handler=ToolCallHandlerStub(),
        adapter=AdapterStub(),
        tool_service=ToolServiceStub(),
        prompt_service=prompt_service,
    )
    command_processor = CommandProcessor(
        config_service, history_service, macro_service, status_service
    )
    tool_service = ToolServiceStub()
    tool_registry = object()

    return RuntimeContext(
        config_service=config_service,
        history_service=history_service,
        llm_service=llm_service,
        macro_service=macro_service,
        status_service=status_service,
        prompt_service=prompt_service,
        command_processor=command_processor,
        tool_service=tool_service,
        tool_registry=tool_registry,
    )


def test_tui_app_starts_and_handles_basic_events() -> None:
    """Verify the TUI app starts and updates presentation buffers."""

    runtime_context = build_runtime_context()
    turn_coordinator = TurnCoordinator()
    tui = TuiApp(
        runtime_context=runtime_context,
        turn_coordinator=turn_coordinator,
        layout=build_layout(),
        event_queue=deque(),
    )

    tui.start()
    tui.enqueue_event(OutputEvent(text="hello"))
    tui.enqueue_event(StatusEvent(text="running"))
    tui.enqueue_event(SubagentResultEvent(task_id="task-1", text="subagent result"))
    tui.enqueue_event(ErrorEvent(text="boom"))
    tui.enqueue_event(InputDraftEvent(draft_text="draft"))
    tui.drain_events()

    snapshot = turn_coordinator.snapshot()
    assert tui.is_running is True
    assert tui.output_buffer == ["hello", "subagent result", "boom"]
    assert tui.status_text == "error"
    assert tui.input_draft == "draft"
    assert tui.layout.output_title == "Output"
    assert tui.output_area.text == "hello\nsubagent result\nboom"
    assert tui.input_area.text == "draft"
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
