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
from monitor_oop.core.infrastructure.request_capacity_service import RequestCapacityService
from monitor_oop.core.infrastructure.rate_limit_service import RateLimitService
from monitor_oop.core.status_service import StatusService
from monitor_oop.core.summarization_service import SummarizationService
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
        summarization_service: SummarizationService,
        command_processor: CommandProcessor,
        tool_service: ToolService,
        tool_registry: ToolRegistry,
        request_capacity_service: RequestCapacityService,
        rate_limit_service: RateLimitService,
        compaction_store,
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
            summarization_service: The summarization service.
            command_processor: The command processor from monitor_oop.core.command_processor.
            tool_service: The tool service.
            tool_registry: The tool registry.
            request_capacity_service: The request capacity service.
            rate_limit_service: The rate limit service.
            compaction_store: The compaction store used for summarization and context compaction boundaries.
            server_app: Optional server application instance.
            logger_service: Optional logger service.
        """
        self._config_service = config_service
        self._history_service = history_service
        self._llm_service = llm_service
        self._macro_service = macro_service
        self._status_service = status_service
        self._prompt_service = prompt_service
        self._summarization_service = summarization_service
        self._logger_service = logger_service
        self._command_processor = command_processor
        self._server_app = server_app
        self._tool_registry = tool_registry
        self._tool_service = tool_service
        self._request_capacity_service = request_capacity_service
        self._rate_limit_service = rate_limit_service
        self._compaction_store = compaction_store
        self._state = AppState()

        if self._logger_service is not None:
            self._logger_service.get_logger(__name__).info("RuntimeContext initialized.")

    @property
    def config_service(self) -> ConfigService:
        """Return the configuration service."""
        return self._config_service

    @property
    def history_service(self) -> HistoryService:
        """Return the history service."""
        return self._history_service

    @property
    def llm_service(self) -> LLMService:
        """Return the language model service."""
        return self._llm_service

    @property
    def macro_service(self) -> MacroService:
        """Return the macro service."""
        return self._macro_service

    @property
    def status_service(self) -> StatusService:
        """Return the status service."""
        return self._status_service

    @property
    def prompt_service(self) -> PromptService:
        """Return the prompt service."""
        return self._prompt_service

    @property
    def summarization_service(self) -> SummarizationService:
        """Return the summarization service."""
        return self._summarization_service

    @property
    def logger_service(self) -> LoggerService | None:
        """Return the optional logger service."""
        return self._logger_service

    @property
    def command_processor(self) -> CommandProcessor:
        """Return the command processor."""
        return self._command_processor

    @property
    def server_app(self):
        """Return the optional server application instance."""
        return self._server_app

    @property
    def tool_registry(self) -> ToolRegistry:
        """Return the tool registry."""
        return self._tool_registry

    @property
    def tool_service(self) -> ToolService:
        """Return the tool service."""
        return self._tool_service

    @property
    def request_capacity_service(self) -> RequestCapacityService:
        """Return the request capacity service."""
        return self._request_capacity_service

    @property
    def rate_limit_service(self) -> RateLimitService:
        """Return the rate limit service."""
        return self._rate_limit_service

    @property
    def compaction_store(self):
        """Return the compaction store used for summarization boundaries."""
        return self._compaction_store

    @property
    def state(self) -> AppState:
        """Return the mutable application state."""
        return self._state

    def create_session(self):
        """Create a conversation session bound to this context."""

        from monitor_oop.core.conversation_session import ConversationSession

        return ConversationSession(self)
