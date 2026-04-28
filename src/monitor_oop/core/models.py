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
class RuntimeConfig:
    """Runtime configuration for a single app instance.

    Note:
        Tracks the source YAML path when loaded from configuration.
    """

    model_name: str = DEFAULT_MODEL
    context_window: int = 400_000
    yaml_path: str = ""


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
    """Mutable application state owned by one runtime instance."""

    mode: AppMode = AppMode.CLI
    running: bool = False
