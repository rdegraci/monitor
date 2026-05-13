"""Tests for the isolated Monitor OOP server app."""
from monitor_oop.core.command_processor import CommandProcessor
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.llm_service import LLMService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.prompt_service import PromptService
from monitor_oop.core.infrastructure.macro_expander import MacroExpander
from monitor_oop.core.infrastructure.macro_store import MacroStore
from monitor_oop.core.infrastructure.prompt_store import PromptStore
from monitor_oop.core.runtime_context import RuntimeContext
from monitor_oop.core.server_app import ServerApp
from monitor_oop.core.status_service import StatusService
from monitor_oop.core.summarization_service import SummarizationService
from unittest.mock import MagicMock


class _ToolService:
    pass


class _ToolRegistry:
    pass


class _LLMClient:
    pass


class _TokenCounter:
    pass


class _ChatFormatter:
    pass


class _SummarizationRequestBuilder:
    pass


class _SummarizationResponseClient:
    pass


class _SummarizationAdapter:
    pass


class _ResponseAdapter:
    pass


class _CompactionStore:
    pass


def build_server_app() -> ServerApp:
    """Build a server app for tests."""

    config_service = ConfigService()
    prompt_store = PromptStore(config_service)
    prompt_service = PromptService(config_service, prompt_store)
    history_service = HistoryService(config_service)
    macro_store = MacroStore()
    macro_expander = MacroExpander()
    macro_service = MacroService(config_service, macro_store, macro_expander)
    status_service = StatusService()
    tool_service = _ToolService()
    tool_registry = _ToolRegistry()
    llm_client = _LLMClient()
    token_counter = _TokenCounter()
    chat_formatter = _ChatFormatter()
    summarization_request_builder = _SummarizationRequestBuilder()
    summarization_response_client = _SummarizationResponseClient()
    response_adapter = _ResponseAdapter()
    summarization_adapter = _SummarizationAdapter()
    compaction_store = _CompactionStore()
    summarization_service = SummarizationService(
        config_service,
        summarization_request_builder,
        summarization_response_client,
        response_adapter,
    )
    llm_service = LLMService(
        config_service,
        prompt_service,
        history_service,
        macro_service,
        llm_client,
        token_counter,
        chat_formatter,
    )
    command_processor = CommandProcessor(config_service, history_service, macro_service, status_service)
    context = RuntimeContext(
        config_service=config_service,
        history_service=history_service,
        macro_service=macro_service,
        status_service=status_service,
        llm_service=llm_service,
        prompt_service=prompt_service,
        command_processor=command_processor,
        tool_service=tool_service,
        tool_registry=tool_registry,
        summarization_service=summarization_service,
        compaction_store=compaction_store,
        request_capacity_service=MagicMock(),
        rate_limit_service=MagicMock(),
    )
    return ServerApp(context)


def test_server_app_convert_messages_to_command() -> None:
    """Verify message conversion uses the last message content."""

    app = build_server_app()

    result = app.convert_messages_to_command([{"content": "first"}, {"content": "second"}])

    assert result == "second"
