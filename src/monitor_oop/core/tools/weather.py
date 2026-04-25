"""Weather tool for Monitor OOP."""
from __future__ import annotations

from monitor_oop.core.tools.tool_models import ToolDefinition


def get_current_weather(location: str, unit: str) -> str:
    """Return a deterministic weather string for a location."""

    return f"The weather in {location} is 12{unit} and cold."


def build_weather_tool_definition() -> ToolDefinition:
    """Build the weather tool definition."""

    return ToolDefinition(
        name="get_current_weather",
        description="Get the current weather in a given location.",
        parameters={
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city and state, e.g. San Francisco, CA",
                },
                "unit": {
                    "type": "string",
                    "description": "Temperature unit, such as F or C",
                },
            },
            "required": ["location", "unit"],
        },
    )


def build_weather_litellm_tool() -> dict:
    """Build the LiteLLM/OpenAI tool schema for the weather tool."""

    tool_definition = build_weather_tool_definition()
    return {
        "type": "function",
        "function": {
            "name": tool_definition.name,
            "description": tool_definition.description,
            "parameters": tool_definition.parameters,
        },
    }
