"""Tests for ToolRegistry in the Monitor OOP core layer."""
from __future__ import annotations

from monitor_oop.core.tools.registry import ToolRegistry
from monitor_oop.core.tools.tool_models import ToolDefinition


def test_tool_registry_register_resolve_and_unregister() -> None:
    """Verify tools can be registered, resolved, listed, and unregistered."""

    registry = ToolRegistry()
    definition = ToolDefinition(
        name="get_current_weather",
        description="Get the current weather.",
        parameters={"type": "object"},
    )

    assert registry.register(definition, lambda **kwargs: "ok") is True
    assert registry.has_tool("get_current_weather") is True
    assert registry.resolve("get_current_weather") == definition
    assert registry.get_handler("get_current_weather") is not None
    assert registry.list_tools()["get_current_weather"] == definition
    assert registry.unregister("get_current_weather") is True
    assert registry.has_tool("get_current_weather") is False
