"""Tests for tool service behavior in Monitor OOP."""
from __future__ import annotations

from monitor_oop.core.tools.registry import ToolRegistry
from monitor_oop.core.tools.tool_models import ToolCall, ToolDefinition, ToolResult
from monitor_oop.core.tools.tool_service import ToolService


def build_weather_tool() -> ToolDefinition:
    """Create a stable weather tool definition for tests."""

    return ToolDefinition(
        name="get_current_weather",
        description="Get the current weather for a location.",
        parameters={
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "unit": {"type": "string"},
            },
            "required": ["location", "unit"],
        },
    )


def get_current_weather(location: str, unit: str) -> str:
    """Return deterministic weather output for tests."""

    return f"The weather in {location} is 12{unit} and cold."


def failing_tool(location: str, unit: str) -> str:
    """Raise a deterministic error for execution failure tests."""

    raise RuntimeError(f"failed for {location} {unit}")


def test_register_and_resolve_tool() -> None:
    """Verify tools can be registered and resolved through the service."""

    registry = ToolRegistry()
    service = ToolService(registry)
    tool = build_weather_tool()

    assert service.register_tool(tool, get_current_weather) is True
    assert service.resolve_tool(tool.name) == tool
    assert service.list_tools()[tool.name] == tool


def test_execute_returns_success_result_for_valid_tool_call() -> None:
    """Verify execution returns a successful tool result."""

    registry = ToolRegistry()
    service = ToolService(registry)
    tool = build_weather_tool()
    assert service.register_tool(tool, get_current_weather) is True

    result = service.execute(
        "get_current_weather",
        {"location": "San Diego, CA", "unit": "F"},
    )

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.tool_name == "get_current_weather"
    assert result.output == "The weather in San Diego, CA is 12F and cold."
    assert result.error == ""


def test_execute_rejects_missing_required_arguments() -> None:
    """Verify argument validation blocks incomplete tool calls."""

    registry = ToolRegistry()
    service = ToolService(registry)
    tool = build_weather_tool()
    assert service.register_tool(tool, get_current_weather) is True

    result = service.execute("get_current_weather", {"location": "San Diego, CA"})

    assert result.success is False
    assert result.output == ""
    assert result.error == "Invalid tool arguments."


def test_execute_rejects_missing_tool_registration() -> None:
    """Verify execution fails clearly when a tool is not registered."""

    service = ToolService(ToolRegistry())

    result = service.execute("missing_tool", {"location": "San Diego, CA", "unit": "F"})

    assert result.success is False
    assert result.output == ""
    assert result.error == "Tool not found: missing_tool"


def test_execute_tool_call_uses_tool_call_object() -> None:
    """Verify ToolCall objects dispatch through the service."""

    registry = ToolRegistry()
    service = ToolService(registry)
    tool = build_weather_tool()
    assert service.register_tool(tool, get_current_weather) is True
    tool_call = ToolCall(
        call_id="call_1",
        tool_name="get_current_weather",
        arguments={"location": "Portland, OR", "unit": "C"},
    )

    result = service.execute_tool_call(tool_call)

    assert result.success is True
    assert result.output == "The weather in Portland, OR is 12C and cold."


def test_build_responses_tools_and_litellm_tools_export_registered_schema() -> None:
    """Verify tool schema export stays consistent across output shapes."""

    registry = ToolRegistry()
    service = ToolService(registry)
    tool = build_weather_tool()
    assert service.register_tool(tool, get_current_weather) is True

    responses_tools = service.build_responses_tools()
    litellm_tools = service.build_litellm_tools()

    assert len(responses_tools) == 1
    assert len(litellm_tools) == 1
    assert responses_tools[0]["name"] == "get_current_weather"
    assert responses_tools[0]["parameters"]["type"] == "object"
    assert litellm_tools[0]["function"]["name"] == "get_current_weather"
    assert litellm_tools[0]["function"]["parameters"]["type"] == "object"


def test_build_follow_up_payloads_preserves_messages_and_envelopes() -> None:
    """Verify multi-item follow-up payload construction keeps input messages intact."""

    service = ToolService(ToolRegistry())
    messages = [{"role": "user", "content": "hello"}]
    results = [
        ("call_1", "item_1", ToolResult(tool_name="get_current_weather", success=True, output="sunny")),
        ("call_2", None, ToolResult(tool_name="get_current_weather", success=False, output="", error="boom")),
    ]

    payload = service.build_follow_up_payloads(messages, results, parent_response_id="resp_1")

    assert payload[0] == messages[0]
    assert len(payload) == 3
    assert payload[1]["call_id"] == "call_1"
    assert payload[1]["output"] == "sunny"
    assert payload[2]["call_id"] == "call_2"
    assert payload[2]["error"] == "boom"


def test_should_continue_after_tool_call_handles_call_and_result_types() -> None:
    """Verify continuation decisions are based on tool call and tool result types."""

    service = ToolService(ToolRegistry())

    assert service.should_continue_after_tool_call(
        ToolCall(call_id="call_1", tool_name="get_current_weather", arguments={})
    ) is True
    assert service.should_continue_after_tool_call(
        ToolResult(tool_name="get_current_weather", success=True, output="ok")
    ) is True
    assert service.should_continue_after_tool_call(
        ToolResult(tool_name="get_current_weather", success=False, output="", error="boom")
    ) is False
    assert service.should_continue_after_tool_call(object()) is False


def test_execute_returns_handler_error_message_on_exception() -> None:
    """Verify handler failures surface as failed tool results."""

    registry = ToolRegistry()
    service = ToolService(registry)
    tool = build_weather_tool()
    assert service.register_tool(tool, failing_tool) is True

    result = service.execute("get_current_weather", {"location": "San Diego, CA", "unit": "F"})

    assert result.success is False
    assert "failed for San Diego, CA F" in result.error
