"""Top-level application coordinator for Monitor OOP."""
from __future__ import annotations

import logging
import sys
from logging import getLogger

from monitor_oop.core.command_processor import CommandProcessor
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.llm_service import LLMService
from monitor_oop.core.logger_service import LoggerService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.runtime_context import RuntimeContext
from monitor_oop.core.status_service import StatusService
from monitor_oop.core.tools.weather import build_weather_tool_definition, get_current_weather
from monitor_oop.core.workflow import reset_config, run_cli, run_script, run_server

logger = getLogger(__name__)


class MonitorApp:
    """Owns startup, mode selection, and lifecycle management."""

    def __init__(self, context: RuntimeContext) -> None:
        self.context = context

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

    def reset_config(self, force: bool = False) -> None:
        """Reset application configuration."""
        reset_config(self, force=force)


def build_app() -> MonitorApp:
    """Build a thin-slice application instance."""
    logger_service = LoggerService()
    logger_service.configure(level=logging.INFO)
    config_service = ConfigService()
    config_service.load_env()
    history_service = HistoryService(config_service)
    llm_service = LLMService(config_service)
    macro_service = MacroService(config_service)
    status_service = StatusService()
    command_processor = CommandProcessor(config_service, history_service, macro_service, status_service)
    context = RuntimeContext(
        config_service=config_service,
        history_service=history_service,
        llm_service=llm_service,
        logger_service=logger_service,
        macro_service=macro_service,
        status_service=status_service,
        command_processor=command_processor,
    )
    context.tool_service.register_tool(build_weather_tool_definition(), get_current_weather)
    return MonitorApp(context)
