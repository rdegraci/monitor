"""Shared data models for the isolated Monitor application."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
    """Runtime configuration for a single app instance."""

    model_name: str = "default"
    context_window: int = 4_096


@dataclass(slots=True)
class Message:
    """A single conversation message."""

    role: str
    content: str


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
