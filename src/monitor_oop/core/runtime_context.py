"""Runtime context for the isolated Monitor application."""
from __future__ import annotations

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.llm_service import LLMService
from monitor_oop.core.logger_service import LoggerService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.models import AppState
from monitor_oop.core.prompt_service import PromptService
from monitor_oop.core.status_service import StatusService
from monitor_oop.core.tools.registry import ToolRegistry
from monitor_oop.core.tools.tool_service import ToolService


class RuntimeContext:
    """Owns process-local services and app state."""

    def __init__(
        self,
        config_service: ConfigService,
        history_service: HistoryService,
        llm_service: LLMService | None,
        macro_service: MacroService,
        status_service: StatusService,
        prompt_service: PromptService,
        command_processor,
        server_app=None,
        tool_service: ToolService | None = None,
        tool_registry: ToolRegistry | None = None,
        logger_service: LoggerService | None = None,
    ) -> None:
        self.config_service = config_service
        self.history_service = history_service
        self.macro_service = macro_service
        self.status_service = status_service
        self.prompt_service = prompt_service
        self.logger_service = logger_service
        self.command_processor = command_processor
        self.server_app = server_app
        self.tool_registry = tool_registry or ToolRegistry()
        self.tool_service = tool_service or ToolService(self.tool_registry)
        if llm_service is not None:
            self.llm_service = llm_service
        else:
            self.llm_service = LLMService(
                self.config_service,
                self.tool_service,
            )
        self.state = AppState()

    def create_session(self):
        """Create a conversation session bound to this context."""

        from monitor_oop.core.conversation_session import ConversationSession

        return ConversationSession(self)
