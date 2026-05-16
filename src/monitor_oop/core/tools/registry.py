"""Tool registry for Monitor OOP."""
from __future__ import annotations

from collections.abc import Callable

from monitor_oop.core.tools.tool_models import ToolDefinition, ToolRegistration


class ToolRegistry:
    """Own registered tool definitions and lookup metadata."""

    def __init__(self) -> None:
        self._registrations: dict[str, ToolRegistration] = {}

    def _get_registration(self, tool_name: str) -> ToolRegistration | None:
        """Return a registration if it exists."""

        return self._registrations.get(tool_name)

    def _create_registration(self, tool: ToolDefinition, handler: Callable[..., str]) -> ToolRegistration:
        """Create a registration entry for a tool definition and handler."""

        return ToolRegistration(definition=tool, handler=handler)

    def register(self, tool: ToolDefinition, handler: Callable[..., str]) -> bool:
        """Register a tool definition and handler."""

        if self._get_registration(tool.name) is not None:
            return False
        self._registrations[tool.name] = self._create_registration(tool, handler)
        return True

    def unregister(self, tool_name: str) -> bool:
        """Remove a tool definition by name."""

        if self._get_registration(tool_name) is None:
            return False
        del self._registrations[tool_name]
        return True

    def resolve(self, tool_name: str) -> ToolDefinition | None:
        """Return a tool definition if it exists."""

        registration = self._get_registration(tool_name)
        if registration is None:
            return None
        return registration.definition

    def get_handler(self, tool_name: str) -> Callable[..., str] | None:
        """Return a handler for a registered tool if available."""

        registration = self._get_registration(tool_name)
        if registration is None:
            return None
        return registration.handler

    def list_tools(self) -> dict[str, ToolDefinition]:
        """Return a copy of registered tools."""

        return {name: registration.definition for name, registration in self._registrations.items()}

    def has_tool(self, tool_name: str) -> bool:
        """Return whether a tool is registered."""

        return self._get_registration(tool_name) is not None
