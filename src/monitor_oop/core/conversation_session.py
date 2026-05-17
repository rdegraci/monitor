"""Conversation session handling for the isolated Monitor application."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from monitor_oop.core.models import CommandType, Message
from monitor_oop.core.runtime_context import RuntimeContext


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConversationTurnResult:
    """Result of processing one conversation turn.

    Attributes:
        assistant_text: The assistant response text generated for the turn.
        status_text: A short status string describing the UI state.
    """

    assistant_text: str
    status_text: str


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

    def _get_compaction_config_service(self):
        """Return the config service when it supports compaction-related methods.

        Returns:
            The current config service if it exposes the methods needed for
            compaction decisions, otherwise None.
        """

        config_service = self.context.config_service
        required_methods = (
            "get_context_window",
            "get_output_window",
            "get_full_model_name",
            "estimate_token_usage",
        )
        for method_name in required_methods:
            if not hasattr(config_service, method_name):
                return None
        return config_service

    def _build_compaction_summary(self) -> str:
        """Build a deterministic summary string for history compaction.

        The summary uses the configured summarization prompt template together
        with the current history length so compaction remains deterministic and
        does not depend on any external summarization call.
        """

        history_snapshot = tuple(self.context.history_service.messages)
        logger.info("History compaction requested; running compaction flow")
        return self.context.summarization_service.summarize(history_snapshot)

    def _estimate_compaction_token_count(self, history_snapshot: tuple[Message, ...]) -> int | None:
        """Estimate token usage for the current history conservatively."""

        config_service = self._get_compaction_config_service()
        if config_service is None:
            return None

        model_name = config_service.get_full_model_name()
        if not model_name:
            return None

        try:
            estimated_token_count = config_service.estimate_token_usage(
                model=model_name,
                messages=list(history_snapshot),
                tools=None,
                previous_response_id=None,
            )
        except Exception:
            logger.exception("Token usage estimation failed; falling back to message lengths")
            return None

        if estimated_token_count is None:
            return None

        return estimated_token_count

    def _maybe_compact_history(self) -> None:
        """Compact history when the history service requests it."""

        history_service = self.context.history_service
        config_service = self._get_compaction_config_service()
        if config_service is None:
            logger.info("Compaction config service unavailable; using legacy turn-budget path")
            should_compact = history_service.should_compact()
            logger.info("Legacy compaction decision: %s", should_compact)
            if should_compact:
                summary_text = self._build_compaction_summary()
                history_service.compact(summary_text)
            return

        history_snapshot = tuple(history_service.messages)
        message_lengths = [len(message.content) for message in history_snapshot]
        context_window = config_service.get_context_window()
        output_window = config_service.get_output_window()

        estimated_token_count = None
        if history_snapshot:
            estimated_token_count = self._estimate_compaction_token_count(history_snapshot)
            if estimated_token_count is None:
                estimated_token_count = sum(message_lengths)

        logger.info(
            "Evaluating compaction with context_window=%s output_window=%s estimated_token_count=%s message_count=%s",
            context_window,
            output_window,
            estimated_token_count,
            len(history_snapshot),
        )
        should_compact = history_service.should_compact(
            context_window=context_window,
            estimated_token_count=estimated_token_count,
            message_lengths=message_lengths,
            output_window=output_window,
        )
        logger.info("Compaction decision: %s", should_compact)
        if should_compact:
            summary_text = self._build_compaction_summary()
            history_service.compact(summary_text)

    def process_user_input(self, user_input: str) -> str | None:
        """Process one user input and return the assistant text.

        Returns None for EXIT commands after stopping the session.
        """

        logger.info("Processing user input")
        result = self.context.command_processor.process(user_input)
        if result.command_type is CommandType.EXIT:
            logger.info("Exit command received; stopping session")
            self._running = False
            return None
        self.context.history_service.append(Message(role="user", content=user_input))
        completion_result = self.context.llm_service.complete(
            user_input, self.context.history_service.messages
        )
        for message in completion_result.messages:
            self.context.history_service.append_message(message)
        self._maybe_compact_history()
        return completion_result.assistant_text

    def submit_input(self, user_input: str) -> ConversationTurnResult | None:
        """Submit one user input and return a UI-friendly turn result.

        Args:
            user_input: The user input to process.

        Returns:
            A ConversationTurnResult containing the assistant response text and
            status text, or None if the input ended the session.
        """

        assistant_text = self.process_user_input(user_input)
        if assistant_text is None:
            return None

        return ConversationTurnResult(
            assistant_text=assistant_text,
            status_text="idle",
        )
