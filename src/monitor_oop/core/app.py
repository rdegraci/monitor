"""Top-level application coordinator for Monitor OOP."""
from __future__ import annotations

import logging
import sys
from logging import getLogger

from monitor_oop.core.application.llm_request_builder import LLMRequestBuilder
from monitor_oop.core.command_processor import CommandProcessor
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.infrastructure.llm_response_client import LLMResponseClient
from monitor_oop.core.infrastructure.macro_expander import MacroExpander
from monitor_oop.core.infrastructure.macro_store import MacroStore
from monitor_oop.core.infrastructure.prompt_store import PromptStore
from monitor_oop.core.llm_adapter import ResponsesOpenAiAdapter
from monitor_oop.core.llm_service import LLMService
from monitor_oop.core.logger_service import LoggerService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.prompt_service import PromptService
from monitor_oop.core.runtime_context import RuntimeContext
from monitor_oop.core.status_service import StatusService
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
        self._tui_app.start()
        self._tui_app.drain_events()
        view = self._tui_app.render()
        print(view, end="")
        return 0

    def reset_config(self, force: bool = False) -> None:
        """Reset application configuration."""
        reset_config(self, force=force)


def build_app() -> MonitorApp:
    """Build a thin-slice application instance."""
    logger_service = LoggerService()
    config_service = ConfigService()
    config_service.load()
    logger_service.configure(level=config_service.get_logging_level())
    app_logger = logger_service.get_logger(__name__)
    app_logger.info("Starting application bootstrap")
    history_service = HistoryService(config_service)
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
    tool_registry = ToolRegistry()
    tool_service = ToolService(tool_registry)
    app_logger.info("Registering weather tool")
    tool_service.register_tool(build_weather_tool_definition(), get_current_weather)
    tool_turn_state = ToolTurnState()
    request_builder = LLMRequestBuilder()
    adapter = ResponsesOpenAiAdapter()
    response_client = LLMResponseClient(config_service, adapter, tool_service)
    tool_call_handler = ToolCallHandler(tool_service, tool_turn_state)
    llm_service = LLMService(
        config_service,
        request_builder,
        response_client,
        tool_call_handler,
        adapter,
        tool_service,
        prompt_service,
    )
    command_processor = CommandProcessor(
        config_service, history_service, macro_service, status_service
    )
    context = RuntimeContext(
        config_service=config_service,
        history_service=history_service,
        llm_service=llm_service,
        logger_service=logger_service,
        macro_service=macro_service,
        status_service=status_service,
        command_processor=command_processor,
        tool_registry=tool_registry,
        tool_service=tool_service,
        prompt_service=prompt_service,
    )
    turn_coordinator = TurnCoordinator()
    tui_app = TuiApp(context, turn_coordinator)
    app_logger.info("Application bootstrap complete after weather tool registration")
    return MonitorApp(context, tui_app=tui_app)
