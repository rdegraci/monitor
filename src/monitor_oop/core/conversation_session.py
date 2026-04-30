"""Conversation session handling for the isolated Monitor application."""
from __future__ import annotations

import logging
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from monitor_oop.core.models import CommandType, Message
from monitor_oop.core.runtime_context import RuntimeContext


logger = logging.getLogger(__name__)


class ConversationSession:
    """Owns the interactive session lifecycle for a single runtime."""

    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self._running = False
        self._prompt_session: PromptSession[str] | None = None

    @property
    def is_running(self) -> bool:
        """Return whether the session is currently running."""

        return self._running

    def _get_history(self) -> Optional[FileHistory]:
        history_file_path = self.context.config_service.get_history_file_path()
        if not history_file_path:
            logger.info("Persistent history disabled; using in-memory prompt session")
            return None
        logger.info("Initializing prompt history from %s", history_file_path)
        return FileHistory(str(history_file_path))

    def _create_prompt_session(self) -> PromptSession[str]:
        history = self._get_history()
        return PromptSession(history=history)

    @property
    def prompt_session(self) -> PromptSession[str]:
        """Return the prompt session, creating it on demand."""

        if self._prompt_session is None:
            self._prompt_session = self._create_prompt_session()
        return self._prompt_session

    def start(self) -> int:
        """Start the session and return an exit code."""

        logger.info("Starting conversation session")
        self._running = True
        self.context.state.running = True
        return 0

    def step(self) -> bool:
        """Run one interactive step."""

        return self._running

    def read_user_input(self) -> str:
        """Read one line of user input using the interactive prompt."""

        logger.info("Prompting user for input")
        return self.prompt_session.prompt("> ")

    def handle_model_switch(self) -> None:
        """Handle model switching behavior for the session."""

        return None

    def process_user_input(self, user_input: str) -> bool:
        """Process one user input and update session state."""

        logger.info("Processing user input")
        result = self.context.command_processor.process(user_input)
        if result.command_type is CommandType.EXIT:
            logger.info("Exit command received; stopping session")
            self._running = False
            self.context.state.running = False
            return False
        self.context.history_service.append(Message(role="user", content=user_input))
        response_text = self.context.llm_service.complete(
            user_input, self.context.history_service.messages
        )
        self.context.history_service.append(
            Message(role="assistant", content=response_text)
        )
        print(response_text)
        return True
