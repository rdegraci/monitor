"""Top-level application coordinator for Monitor OOP."""
from __future__ import annotations

from logging import getLogger
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

from monitor_oop.core.application.llm_request_builder import LLMRequestBuilder
from monitor_oop.core.command_processor import CommandProcessor
from monitor_oop.core.compaction_store import CompactionStore
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.conversation_session import ConversationSession
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.infrastructure.llm_response_client import LLMResponseClient
from monitor_oop.core.infrastructure.macro_expander import MacroExpander
from monitor_oop.core.infrastructure.macro_store import MacroStore
from monitor_oop.core.infrastructure.prompt_store import PromptStore
from monitor_oop.core.infrastructure.rate_limit_service import RateLimitService
from monitor_oop.core.infrastructure.request_capacity_service import RequestCapacityService
from monitor_oop.core.llm_adapter import ResponsesOpenAiAdapter
from monitor_oop.core.llm_service import LLMService
from monitor_oop.core.logger_service import LoggerService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.prompt_service import PromptService
from monitor_oop.core.runtime_context import RuntimeContext
from monitor_oop.core.status_service import StatusService
from monitor_oop.core.summarization_service import SummarizationService
from monitor_oop.core.tool_turn_state import ToolTurnState
from monitor_oop.core.presentation.turn_coordinator import TurnCoordinator
from monitor_oop.core.tools.registry import ToolRegistry
from monitor_oop.core.tools.tool_call_handler import ToolCallHandler
from monitor_oop.core.tools.tool_service import ToolService
from monitor_oop.core.tools.weather import build_weather_tool_definition, get_current_weather
from monitor_oop.core.presentation.tui import TuiApp
from monitor_oop.core.workflow import reset_config, run_cli, run_script, run_server

logger = getLogger(__name__)


class MonitorApp:
    """Owns startup, mode selection, and lifecycle management."""

    def __init__(self, context: RuntimeContext, tui_app: TuiApp | None = None) -> None:
        self._context = context
        self._tui_app = tui_app

    @property
    def context(self) -> RuntimeContext:
        """Get the application runtime context."""
        return self._context

    @property
    def tui_app(self) -> TuiApp | None:
        """Get the optional TUI application."""
        return self._tui_app

    def _has_openai_api_key(self) -> bool:
        """Check whether the OpenAI API key is configured."""
        return bool(self.context.config_service.get_openai_api_key())

    def _append_tui_output(self, text: str) -> None:
        """Append text to the TUI output buffer."""
        if self._tui_app is not None:
            self._tui_app.enqueue_input_draft_event(text)

    def _append_tui_conversation(self, user_text: str, assistant_text: str) -> None:
        """Append a user turn and assistant reply to the TUI buffer."""
        self._append_tui_output(f"> {user_text}")
        self._append_tui_output(assistant_text)

    def _process_tui_turn(
        self, session: ConversationSession, text: str
    ) -> None:
        """Process one TUI user turn and append any assistant reply."""
        response_text = session.process_user_input(text)
        if response_text is not None:
            self._append_tui_conversation(text, response_text)

    def run(self) -> int:
        """Run the default CLI workflow."""
        if not self._has_openai_api_key():
            return 1
        return run_cli(self)

    def run_cli(self) -> int:
        """Run the CLI workflow."""
        return run_cli(self)

    def run_server(self) -> int:
        """Run the server workflow."""
        return run_server(self)

    def run_script(self, script_path: str) -> int:
        """Run a script workflow."""
        return run_script(self, script_path)

    def run_tui(self) -> int:
        """Run the TUI workflow."""
        if self._tui_app is None:
            return 1
        logger.info("Starting TUI mode")
        return self._tui_app.run()

    def reset_config(self, force: bool = False) -> None:
        """Reset application configuration."""
        reset_config(self, force=force)


def build_app(quiet_bootstrap: bool = False) -> MonitorApp:
    """Build a thin-slice application instance.

    Args:
        quiet_bootstrap: When True, suppress bootstrap log emission.
    """
    logger_service = LoggerService()
    config_service = ConfigService()
    config_service.load()
    log_file_path = config_service.get_log_file_path()
    logger_service.configure(
        level=config_service.get_logging_level(),
        log_file_path=log_file_path,
    )
    app_logger = logger_service.get_logger(__name__)
    app_logger.info("Starting application bootstrap")
    if quiet_bootstrap:
        app_logger.info("Bootstrap logging configured for TUI mode with file-only output")
    else:
        app_logger.info("Bootstrap logging configured for REPL mode with file-only output")
    compaction_dir_path = config_service.get_compaction_dir_path()
    if compaction_dir_path:
        compaction_store = CompactionStore(Path(compaction_dir_path))
    else:
        app_logger.warning(
            "No writable compaction directory available; compaction summaries will not be persisted"
        )
        compaction_store = None
    history_service = HistoryService(config_service, compaction_store)
    prompt_store = PromptStore(config_service)
    macro_store = MacroStore("Monitor OOP")
    macro_expander = MacroExpander("{{", "}}")
    macro_service = MacroService(config_service, macro_store, macro_expander)
    app_logger.info("Loading macros during bootstrap")
    macro_service.load()
    prompt_service = PromptService(config_service, prompt_store)
    app_logger.info("Loading prompts during bootstrap")
    prompt_service.load()
    status_service = StatusService()
    request_capacity_service = RequestCapacityService(config_service)
    rate_limit_service = RateLimitService(config_service)
    llm_request_builder = LLMRequestBuilder()
    adapter = ResponsesOpenAiAdapter()
    tool_registry = ToolRegistry()
    tool_service = ToolService(tool_registry)
    app_logger.info("Registering weather tool")
    tool_service.register_tool(build_weather_tool_definition(), get_current_weather)
    tool_turn_state = ToolTurnState()
    response_client = LLMResponseClient(
        config_service,
        adapter,
        tool_service,
        request_capacity_service,
        rate_limit_service,
    )
    llm_service = LLMService(
        config_service,
        llm_request_builder,
        response_client,
        ToolCallHandler(tool_service, tool_turn_state),
        adapter,
        tool_service,
        prompt_service,
    )
    summarization_prompt_template = config_service.get_summarization_prompt_template()
    summarization_service = SummarizationService(
        config_service,
        llm_request_builder,
        response_client,
        adapter,
        summarization_prompt_template,
    )
    app_logger.info("Initializing summarization service during bootstrap")
    command_processor = CommandProcessor(
        config_service, history_service, macro_service, status_service
    )
    context = RuntimeContext(
        config_service=config_service,
        history_service=history_service,
        compaction_store=compaction_store,
        llm_service=llm_service,
        logger_service=logger_service,
        macro_service=macro_service,
        status_service=status_service,
        summarization_service=summarization_service,
        command_processor=command_processor,
        tool_registry=tool_registry,
        tool_service=tool_service,
        prompt_service=prompt_service,
        request_capacity_service=request_capacity_service,
        rate_limit_service=rate_limit_service,
    )
    app_logger.info(
        "Runtime config: model=%s alias=%s context=%s output=%s turns=%s tpm=%s rpm=%s provider=%s full=%s",
        config_service.get_api_model_name(),
        config_service.get_model_alias(),
        config_service.get_context_window(),
        config_service.get_output_window(),
        config_service.get_conversation_turn_budget(),
        config_service.get_tokens_per_minute(),
        config_service.get_requests_per_minute(),
        config_service.get_provider(),
        config_service.get_full_model_name(),
    )
    turn_coordinator = TurnCoordinator()
    tui_app = TuiApp(context, turn_coordinator)
    app_logger.info("Application bootstrap complete after weather tool registration")
    return MonitorApp(context, tui_app=tui_app)
