"""Tool subsystem data models for Monitor OOP."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class ToolDefinition:
    """Describe a registered tool."""

    name: str
    description: str
    parameters: dict[str, object]


@dataclass(slots=True)
class ToolCall:
    """Represent a tool request from a model response."""

    call_id: str
    tool_name: str
    arguments: dict[str, object]


@dataclass(slots=True)
class ToolResult:
    """Represent the outcome of a tool execution."""

    tool_name: str
    success: bool
    output: str
    error: str = ""


@dataclass(slots=True)
class ToolRegistration:
    """Internal registry entry for a tool."""

    definition: ToolDefinition
    handler: Callable[..., str]
