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


def build_session(conversation_max_turns: int = 2) -> ConversationSession:
    """Build a conversation session with deterministic test doubles."""

    runtime_config = RuntimeConfig()
    runtime_config.conversation_turn_budget = conversation_max_turns
    runtime_config.summarization_settings.prompt_template = "summary {message_count}"
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


def test_estimate_compaction_token_count_handles_message_dataclasses() -> None:
    """The estimator must accept Message dataclasses by converting to request dicts.

    Regression: history items are Message dataclass instances, not dicts;
    passing them directly raised AttributeError inside the estimator and
    silently disabled the context-window compaction trigger.
    """

    session = build_session()
    # Configure a model so the estimator path is reached.
    session.context.config_service._config.full_model_name = "openai/gpt-4o"

    snapshot = (
        Message(role="user", content="hello world"),
        Message(role="assistant", content="hi there, how can I help?"),
    )

    estimated = session._estimate_compaction_token_count(snapshot)

    assert isinstance(estimated, int)
    assert estimated > 0


def test_estimate_compaction_token_count_returns_none_when_model_missing() -> None:
    """The estimator should short-circuit when no model is configured."""

    session = build_session()
    # full_model_name defaults to None on RuntimeConfig; verify short-circuit.
    snapshot = (Message(role="user", content="hello"),)

    assert session._estimate_compaction_token_count(snapshot) is None
