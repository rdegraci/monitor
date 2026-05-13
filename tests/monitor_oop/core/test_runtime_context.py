"""Tests for the isolated Monitor OOP runtime context."""
from unittest.mock import MagicMock

from monitor_oop.core.command_processor import CommandProcessor
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.infrastructure.macro_expander import MacroExpander
from monitor_oop.core.infrastructure.macro_store import MacroStore
from monitor_oop.core.infrastructure.prompt_store import PromptStore
from monitor_oop.core.llm_service import LLMService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.prompt_service import PromptService
from monitor_oop.core.runtime_context import RuntimeContext
from monitor_oop.core.status_service import StatusService
from monitor_oop.core.summarization_service import SummarizationService


def test_runtime_context_create_session() -> None:
    """Verify runtime context creates a conversation session."""

    config_service = ConfigService()
    history_service = HistoryService(config_service)
    macro_store = MacroStore("monitor_oop")
    macro_expander = MacroExpander("{{", "}}")
    config_service = ConfigService()

    class _LLMConfig:
        model = "test-model"

    class _Tokenizer:
        def count_tokens(self, text: str) -> int:
            return len(text.split())

    class _MessageFactory:
        def create(self, role: str, content: str) -> dict[str, str]:
            return {"role": role, "content": content}

    class _RequestBuilder:
        pass

    class _ResponseClient:
        pass

    class _ToolCallHandler:
        pass

    class _Adapter:
        pass

    class _ConversationFactory:
        pass

    class _CompactionStore:
        pass

    llm_service = LLMService(
        config_service,
        _RequestBuilder(),
        _ResponseClient(),
        _ToolCallHandler(),
        _Adapter(),
        object(),
        object(),
    )
    macro_service = MacroService(config_service, macro_store, macro_expander)
    prompt_store = PromptStore(config_service)
    prompt_service = PromptService(config_service, prompt_store)
    status_service = StatusService()
    summarization_service = SummarizationService(
        config_service,
        _RequestBuilder(),
        _ResponseClient(),
        _Adapter(),
    )
    command_processor = CommandProcessor(config_service, history_service, macro_service, status_service)
    tool_service = object()
    tool_registry = object()
    context = RuntimeContext(
        config_service=config_service,
        history_service=history_service,
        llm_service=llm_service,
        macro_service=macro_service,
        prompt_service=prompt_service,
        status_service=status_service,
        summarization_service=summarization_service,
        command_processor=command_processor,
        tool_service=tool_service,
        tool_registry=tool_registry,
        request_capacity_service=MagicMock(),
        rate_limit_service=MagicMock(),
        compaction_store=_CompactionStore(),
    )

    session = context.create_session()

    assert session.context is context
    assert context.summarization_service is summarization_service
