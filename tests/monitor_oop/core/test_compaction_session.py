"""Tests for compaction orchestration in the conversation session."""
from __future__ import annotations

from dataclasses import dataclass
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
from monitor_oop.core.models import RuntimeConfig
from monitor_oop.core.prompt_service import PromptService
from monitor_oop.core.runtime_context import RuntimeContext
from monitor_oop.core.status_service import StatusService
from monitor_oop.core.summarization_service import SummarizationService


@dataclass(slots=True)
class _FakeRequestBuilder:
    """Minimal request builder stub for session tests."""

    def build_input(self, user_input, history):
        return [user_input, history]

    def build_summarization_input(self, prompt_text, message_history, token_limit):
        return [prompt_text, message_history, token_limit]


@dataclass(slots=True)
class _FakeResponseClient:
    """Minimal response client stub for session tests."""

    def create_response(self, request_input, previous_response_id=None):
        return type("Response", (), {"id": "response-1"})()


@dataclass(slots=True)
class _FakeToolCallHandler:
    """Minimal tool-call handler stub for session tests."""

    def execute_tool_calls(self, request_input, response):
        return request_input, False


@dataclass(slots=True)
class _FakeAdapter:
    """Minimal LLM adapter stub for session tests."""

    def extract_text(self, response):
        return "assistant response"


@dataclass(slots=True)
class _FakeToolService:
    """Minimal tool service stub for session tests."""

    def build_responses_tools(self):
        return []


@dataclass(slots=True)
class _FakeToolRegistry:
    """Minimal tool registry stub for session tests."""


@dataclass(slots=True)
class _FakeCompactionStore:
    """Minimal compaction store stub for session tests."""


class _StubConfigService(ConfigService):
    def __init__(self, runtime_config: RuntimeConfig) -> None:
        super().__init__(initial_config=runtime_config)

    @property
    def compaction_config(self):
        return self._config.summarization


class _FakeSummarizationService:
    def summarize(self, messages, prompt_template) -> str:
        return f"summary {len(messages)}"


def build_session(conversation_max_turns: int = 2) -> ConversationSession:
    """Build a conversation session with deterministic test doubles."""

    runtime_config = RuntimeConfig()
    runtime_config.conversation_turn_budget = conversation_max_turns
    runtime_config.summarization.prompt_template = "summary {message_count}"
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
    summarization_service = SummarizationService(
        config_service=config_service,
        request_builder=request_builder,
        response_client=response_client,
        response_adapter=adapter,
    )
    llm_service = LLMService(
        config_service=config_service,
        request_builder=request_builder,
        response_client=response_client,
        tool_call_handler=_FakeToolCallHandler(),
        adapter=adapter,
        tool_service=_FakeToolService(),
        prompt_service=prompt_service,
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

    result = session.submit_input("hello")

    assert result is not None
    assert result.status_text == "idle"

    history_snapshot = session.context.history_service.snapshot()
    assert any(message.role == "system" for message in history_snapshot)
    assert any(message.role == "assistant" and message.content == "assistant response" for message in history_snapshot)
