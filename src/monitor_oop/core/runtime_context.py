"""Runtime context for the isolated Monitor application."""
from __future__ import annotations

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.models import AppState
from monitor_oop.core.status_service import StatusService


class RuntimeContext:
    """Owns process-local services and app state."""

    def __init__(
        self,
        config_service: ConfigService,
        history_service: HistoryService,
        macro_service: MacroService,
        status_service: StatusService,
        command_processor,
        server_app=None,
    ) -> None:
        self.config_service = config_service
        self.history_service = history_service
        self.macro_service = macro_service
        self.status_service = status_service
        self.command_processor = command_processor
        self.server_app = server_app
        self.state = AppState()

    def create_session(self):
        """Create a conversation session bound to this context."""

        from monitor_oop.core.conversation_session import ConversationSession

        return ConversationSession(self)
