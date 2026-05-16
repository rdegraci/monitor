"""Tool subsystem data models for Monitor OOP."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


def _normalize_tool_name(name: str) -> str:
    """Hook for future tool-name normalization."""

    return name


def _validate_tool_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Hook for future tool-parameter validation."""

    return parameters


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
    response_item_id: str | None = None


@dataclass(slots=True)
class ToolResult:
    """Represent the outcome of a tool execution."""

    tool_name: str
    success: bool
    output: str
    error: str = ""


@dataclass(slots=True)
class ToolOutputEnvelope:
    """Represent the bookkeeping record for tool output aggregation."""

    call_id: str
    response_item_id: str | None
    parent_response_id: str | None
    result: ToolResult | None


@dataclass(slots=True)
class ToolRegistration:
    """Internal registry entry for a tool."""

    definition: ToolDefinition
    handler: Callable[..., str]
