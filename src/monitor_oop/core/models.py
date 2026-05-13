"""Shared data models for the isolated Monitor application."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


DEFAULT_MODEL = "openai/gpt-5.4-mini"


class AppMode(str, Enum):
    """Supported application runtime modes."""

    CLI = "cli"
    SERVER = "server"
    SCRIPT = "script"


class CommandType(str, Enum):
    """Supported command classifications."""

    EXIT = "exit"
    MODEL = "model"
    MACRO = "macro"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class SummarizationSettings:
    """Settings used to compact conversation history.

    Attributes:
        token_limit: Maximum tokens allowed in a generated summary.
        prompt_template: Template used to instruct the summarizer.
    """

    token_limit: int = 4000
    prompt_template: str = (
        "Summarize the conversation history concisely while preserving important "
        "context, decisions, constraints, and open tasks."
    )

    @property
    def prompt(self) -> str:
        """Return the summarization prompt template."""

        return self.prompt_template


@dataclass(slots=True)
class RuntimeConfig:
    """Runtime configuration for a single app instance.

    Note:
        Summarization settings include prompt and token limit configuration.
        Tracks the source YAML path when loaded from configuration.
        The history directory and prompt history filename are used to resolve a persistent FileHistory path.
        The summary settings and conversation turn budget are used by deterministic compaction flows.
    """

    model_name: str = DEFAULT_MODEL
    model_alias: str | None = None
    context_window: int = 400_000
    output_window: int = 32_000
    conversation_turn_budget: int = 128
    summarization_settings: SummarizationSettings = field(
        default_factory=SummarizationSettings
    )
    yaml_path: str = ""
    history_dir: str = "history"
    prompt_history_filename: str = "prompt_history"
    rate_limit_requests: int | None = None
    rate_limit_tokens: int | None = None
    rate_limit_window_seconds: int | None = None
    tokens_per_minute: int | None = None
    requests_per_minute: int | None = None
    provider: str | None = None
    full_model_name: str | None = None

    @property
    def summarization(self) -> SummarizationSettings:
        """Return the summarization settings object used for compaction."""

        return self.summarization_settings

    @property
    def compaction_config(self) -> SummarizationSettings:
        """Return the compaction settings alias used for compaction."""

        return self.summarization_settings

    @property
    def conversation_max_turns(self) -> int:
        """Return the maximum number of conversation turns to retain."""

        return self.conversation_turn_budget


@dataclass(slots=True)
class Message:
    """A single conversation message."""

    role: str
    content: str


@dataclass(slots=True)
class History:
    """Owned conversation history state.

    Attributes:
        messages: Conversation messages in chronological order.
    """

    _messages: list[Message] = field(default_factory=list)

    def append(self, message: Message) -> None:
        """Append a message to the history.

        Args:
            message: The message to append.
        """

        self._messages.append(message)

    def trim(self, count: int) -> None:
        """Keep only the newest messages in the history.

        Args:
            count: The number of newest messages to keep.
        """

        if count <= 0:
            self._messages.clear()
            return
        self._messages[:] = self._messages[-count:]

    def clear(self) -> None:
        """Remove all messages from the history."""

        self._messages.clear()

    def snapshot(self) -> list[Message]:
        """Return a copy of the current message list."""

        return list(self._messages)


@dataclass(slots=True)
class CommandResult:
    """Structured command processing result."""

    command_type: CommandType
    handled: bool = False
    message: str = ""


@dataclass(slots=True)
class AppState:
    """Application-wide state for one runtime instance."""

    mode: AppMode = AppMode.CLI
