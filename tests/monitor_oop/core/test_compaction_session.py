"""Tests for compaction orchestration in the conversation session."""
from __future__ import annotations

from unittest.mock import MagicMock

from monitor_oop.core.command_processor import CommandProcessor
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.conversation_session import ConversationSession
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.infrastructure.macro_expander import MacroExpander
from monitor_oop.core.infrastructure.macro_store import MacroStore
from monitor_oop.core.infrastructure.prompt_store import PromptStore
from monitor_oop.core.llm_service import LLMService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.models import Message
from monitor_oop.core.models import RuntimeConfig
from monitor_oop.core.prompt_service import PromptService
from monitor_oop.core.runtime_context import RuntimeContext
from monitor_oop.core.status_service import StatusService
from monitor_oop.core.summarization_service import SummarizationService


class _FakeRequestBuilder:
    """Minimal request builder stub for session tests."""

    def build_input(self, history):
        return [history]

    def build_summarization_input(self, prompt_text, message_history):
        return [prompt_text, message_history]


class _FakeResponseClient:
    """Minimal response client stub for session tests."""

    def create_response(
        self, request_input, previous_response_id=None, max_output_tokens=None
    ):
        return type("Response", (), {"id": "response-1"})()


class _FakeToolCallHandler:
    """Minimal tool-call handler stub for session tests."""

    def execute_tool_calls(self, request_input, response):
        return request_input, False


class _FakeAdapter:
    """Minimal LLM adapter stub for session tests."""

    def extract_text(self, response):
        if hasattr(response, "assistant_text"):
            return response.assistant_text
        if hasattr(response, "output_text"):
            return response.output_text
        return ""


class _FakeToolService:
    """Minimal tool service stub for session tests."""

    def build_responses_tools(self):
        return []


class _FakeToolRegistry:
    """Minimal tool registry stub for session tests."""


class _FakeCompactionStore:
    """Minimal compaction store stub for session tests."""


class _StubConfigService(ConfigService):
    def __init__(self, runtime_config: RuntimeConfig) -> None:
        super().__init__(initial_config=runtime_config)


class _FakeSummarizationService:
    def __init__(self, config_service: _StubConfigService) -> None:
        self._config_service = config_service

    def summarize(self, messages) -> str:
        prompt_template = self._config_service.get_summarization_prompt_template()
        return f"{prompt_template} | summary {len(messages)}"


def build_session(
    conversation_max_turns: int = 2,
    full_model_name: str | None = None,
    context_window: int | None = None,
) -> ConversationSession:
    """Build a conversation session with deterministic test doubles."""

    runtime_config = RuntimeConfig()
    runtime_config.conversation_turn_budget = conversation_max_turns
    runtime_config.summarization_settings.prompt_template = "summary {message_count}"
    if full_model_name is not None:
        runtime_config.full_model_name = full_model_name
    if context_window is not None:
        runtime_config.context_window = context_window
    config_service = _StubConfigService(runtime_config)
    history_service = HistoryService(config_service)
    macro_store = MacroStore("monitor")
    macro_expander = MacroExpander("{{", "}}")
    macro_service = MacroService(config_service, macro_store, macro_expander)
    status_service = StatusService()
    prompt_store = PromptStore(config_service)
    prompt_service = PromptService(config_service, prompt_store)
    request_builder = _FakeRequestBuilder()
    response_client = _FakeResponseClient()
    adapter = _FakeAdapter()
    summarization_service = _FakeSummarizationService(config_service)
    llm_service = LLMService(
        config_service=config_service,
        request_builder=request_builder,
        response_client=response_client,
        tool_call_handler=_FakeToolCallHandler(),
        adapter=adapter,
        tool_service=_FakeToolService(),
        prompt_service=prompt_service,
    )
    llm_service.complete = MagicMock(
        return_value=type(
            "Completion",
            (),
            {
                "assistant_text": "assistant response",
                "messages": [Message(role="assistant", content="assistant response")],
            },
        )()
    )
    command_processor = CommandProcessor(
        config_service,
        history_service,
        macro_service,
        status_service,
    )
    context = RuntimeContext(
        config_service=config_service,
        history_service=history_service,
        macro_service=macro_service,
        status_service=status_service,
        command_processor=command_processor,
        llm_service=llm_service,
        prompt_service=prompt_service,
        tool_service=_FakeToolService(),
        tool_registry=_FakeToolRegistry(),
        compaction_store=_FakeCompactionStore(),
        summarization_service=summarization_service,
        request_capacity_service=MagicMock(),
        rate_limit_service=MagicMock(),
    )
    return ConversationSession(context)


def test_conversation_session_compacts_history_after_response() -> None:
    """ConversationSession should compact history once the threshold is exceeded."""

    session = build_session(conversation_max_turns=1)
    session.start()

    history_before = session.context.history_service.snapshot()

    result = session.submit_input("hello")

    assert result is not None
    assert result.status_text == "idle"

    history_after = session.context.history_service.snapshot()
    assert history_after != history_before
    assert any(message.role == "system" for message in history_after)
    assert any(message.role == "assistant" and message.content == "assistant response" for message in history_after)
    assert history_after[-1].role == "assistant"
    assert history_after[-1].content == "assistant response"


def test_conversation_session_preserves_tool_call_cluster_during_compaction() -> None:
    """ConversationSession should preserve tool-call clusters during compaction."""

    session = build_session(conversation_max_turns=1)
    session.start()

    history_service = session.context.history_service
    history_service.append_message(
        Message(role="user", content="what is the weather?", response_id="user-response-1")
    )
    history_service.append_message(
        Message(
            role="assistant",
            content="calling tool",
            response_id="assistant-response-1",
            parent_response_id="user-response-1",
            tool_calls=[{"id": "tool-call-1", "name": "weather_lookup"}],
        )
    )
    history_service.append_message(
        Message(
            role="tool",
            content="sunny",
            response_id="tool-response-1",
            parent_response_id="assistant-response-1",
            tool_call_id="tool-call-1",
        )
    )
    history_service.append_message(
        Message(
            role="assistant",
            content="it is sunny",
            response_id="assistant-response-2",
            parent_response_id="tool-response-1",
        )
    )

    history_service.compact("deterministic summary")

    preserved_history = history_service.snapshot()
    assert any(message.role == "system" for message in preserved_history)
    assert any(
        message.role == "assistant"
        and message.content == "calling tool"
        and message.response_id == "assistant-response-1"
        and message.parent_response_id == "user-response-1"
        and message.tool_calls == [{"id": "tool-call-1", "name": "weather_lookup"}]
        for message in preserved_history
    )
    assert any(
        message.role == "tool"
        and message.content == "sunny"
        and message.response_id == "tool-response-1"
        and message.parent_response_id == "assistant-response-1"
        and message.tool_call_id == "tool-call-1"
        for message in preserved_history
    )
    assert any(
        message.role == "assistant"
        and message.content == "it is sunny"
        and message.response_id == "assistant-response-2"
        and message.parent_response_id == "tool-response-1"
        for message in preserved_history
    )


def test_context_window_compaction_fires_when_history_exceeds_soft_threshold() -> None:
    """Regression: context-window compaction must fire when input tokens cross the threshold.

    Earlier, ``ConversationSession`` passed ``Message`` dataclass instances
    where the estimator expected dicts; the estimator raised inside a broad
    ``except`` and silently returned ``None``, leaving the context-window
    branch of ``should_compact`` permanently false. This test seeds enough
    content that compaction can only fire via the context-window branch
    (the turn budget is set high enough that it cannot trip) and asserts
    that compaction actually happens — observable purely through
    ``submit_input`` and ``history_service.snapshot()``.
    """

    # Tight context window so a few large messages cross the 50% soft trigger;
    # very generous turn budget so we know compaction fires via context-window
    # pressure rather than via the turn-budget cliff.
    session = build_session(
        conversation_max_turns=1000,
        full_model_name="openai/gpt-4o",
        context_window=1000,
    )
    session.start()

    history_service = session.context.history_service
    for _ in range(20):
        history_service.append(Message(role="user", content="x" * 400))

    snapshot_before = history_service.snapshot()
    assert len(snapshot_before) == 20

    session.submit_input("trigger")

    snapshot_after = history_service.snapshot()
    # Compaction inserted a system summary at the head and shrank history.
    assert snapshot_after[0].role == "system"
    assert len(snapshot_after) < len(snapshot_before)


def test_compaction_does_not_fire_when_history_is_small_and_model_unset() -> None:
    """Sanity counterpart: no compaction when neither trigger is tripped."""

    session = build_session(conversation_max_turns=1000)
    session.start()

    history_service = session.context.history_service
    history_service.append(Message(role="user", content="hello"))

    session.submit_input("hi")

    snapshot = history_service.snapshot()
    # No system summary should have been inserted.
    assert all(message.role != "system" for message in snapshot)


def test_compaction_emits_compacting_then_working_phase_status() -> None:
    """The session should signal 'compacting' before summarize and 'working' after.

    Lets the TUI surface mid-turn summarization latency instead of a flat
    'working' indicator. Reverse order would leave the indicator stuck on
    'compacting' after the summarization call completes.
    """

    session = build_session(conversation_max_turns=1)
    session.start()

    phase_calls: list[str] = []
    session.context.set_status_listener(phase_calls.append)

    session.submit_input("hello")

    assert phase_calls == ["compacting", "working"]


def test_compaction_emits_working_status_even_if_summarize_raises() -> None:
    """The 'working' restore must fire even when summarization throws."""

    session = build_session(conversation_max_turns=1)
    session.start()

    def _raise(_messages):
        raise RuntimeError("simulated summarizer failure")

    session.context.summarization_service.summarize = _raise

    phase_calls: list[str] = []
    session.context.set_status_listener(phase_calls.append)

    try:
        session.submit_input("hello")
    except RuntimeError:
        # The session does not currently swallow summarizer exceptions; the
        # invariant under test is the status restoration, not the error flow.
        pass

    assert phase_calls == ["compacting", "working"]
