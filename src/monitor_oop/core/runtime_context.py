"""Runtime context for the isolated Monitor application."""
from __future__ import annotations

from monitor_oop.core.command_processor import CommandProcessor
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
        llm_service: LLMService,
        macro_service: MacroService,
        status_service: StatusService,
        prompt_service: PromptService,
        command_processor: CommandProcessor,
        tool_service: ToolService,
        tool_registry: ToolRegistry,
        server_app=None,
        logger_service: LoggerService | None = None,
    ) -> None:
        """Initialize the runtime context.

        Args:
            config_service: The configuration service.
            history_service: The history service.
            llm_service: The language model service.
            macro_service: The macro service.
            status_service: The status service.
            prompt_service: The prompt service.
            command_processor: The command processor from monitor_oop.core.command_processor.
            tool_service: The tool service.
            tool_registry: The tool registry.
            server_app: Optional server application instance.
            logger_service: Optional logger service.
        """
        self.config_service = config_service
        self.history_service = history_service
        self.llm_service = llm_service
        self.macro_service = macro_service
        self.status_service = status_service
        self.prompt_service = prompt_service
        self.logger_service = logger_service
        self.command_processor = command_processor
        self.server_app = server_app
        self.tool_registry = tool_registry
        self.tool_service = tool_service
        self.state = AppState()

        if self.logger_service is not None:
            self.logger_service.get_logger(__name__).info("RuntimeContext initialized.")

    def create_session(self):
        """Create a conversation session bound to this context."""

        from monitor_oop.core.conversation_session import ConversationSession

        return ConversationSession(self)
