"""Tests for tool service behavior in Monitor OOP."""
from __future__ import annotations

from monitor_oop.core.tools import (
    build_tool_call_output,
    build_weather_tool_definition,
    extract_tool_calls,
    normalize_tool_arguments,
)
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


def test_weather_tool_returns_deterministic_result() -> None:
    """Verify the weather tool returns the expected stubbed output."""

    result = get_current_weather("San Diego, CA", "F")

    assert result == "The weather in San Diego, CA is 12F and cold."


def test_tool_registry_register_resolve_and_list() -> None:
    """Verify the registry stores tools privately and returns copies."""

    registry = ToolRegistry()
    definition = build_weather_tool_definition()

    assert registry.register(definition, get_current_weather) is True
    assert registry.has_tool(definition.name) is True
    assert registry.resolve(definition.name) == definition
    listed = registry.list_tools()
    assert listed[definition.name] == definition


def test_tool_service_executes_registered_tool() -> None:
    """Verify the tool service can execute a registered tool."""

    registry = ToolRegistry()
    service = ToolService(registry)
    definition = build_weather_tool_definition()

    assert service.register_tool(definition, get_current_weather) is True
    result = service.execute(
        "get_current_weather",
        {"location": "San Diego, CA", "unit": "F"},
    )

    assert result.success is True
    assert "San Diego, CA" in result.output


def test_tool_service_build_litellm_tools_exports_registered_schema() -> None:
    """Verify the tool service exports the registered tool schema for LiteLLM."""

    registry = ToolRegistry()
    service = ToolService(registry)
    definition = build_weather_tool_definition()

    assert service.register_tool(definition, get_current_weather) is True

    litellm_tools = service.build_litellm_tools()

    assert isinstance(litellm_tools, list)
    assert len(litellm_tools) == 1

    tool_schema = litellm_tools[0]
    assert tool_schema["type"] == "function"

    function_schema = tool_schema["function"]
    assert function_schema["name"] == "get_current_weather"
    assert function_schema["description"] == definition.description
    assert isinstance(function_schema["parameters"], dict)
    assert function_schema["parameters"]["type"] == "object"


def test_extract_tool_calls_parses_single_function_call_from_object_output() -> None:
    """Verify extract_tool_calls handles a single Responses-style object-shaped tool call."""

    response = type(
        "Response",
        (),
        {
            "output": [
                type(
                    "Message",
                    (),
                    {
                        "type": "message",
                        "content": [
                            type(
                                "Text",
                                (),
                                {
                                    "type": "text",
                                    "text": "I should check the weather before answering.",
                                },
                            )()
                        ],
                    },
                )(),
                type(
                    "ToolCall",
                    (),
                    {
                        "type": "function_call",
                        "tool_name": "get_current_weather",
                        "arguments": '{"location": "San Diego, CA", "unit": "F"}',
                        "call_id": "call_123",
                    },
                )(),
            ],
        },
    )()

    tool_calls = extract_tool_calls(response.output)

    assert isinstance(tool_calls, list)
    assert len(tool_calls) == 1
    tool_call = tool_calls[0]
    assert tool_call.tool_name == "get_current_weather"
    assert tool_call.arguments == {"location": "San Diego, CA", "unit": "F"}
    assert tool_call.call_id == "call_123"


def test_extract_tool_calls_parses_multiple_function_calls_from_dict_output() -> None:
    """Verify extract_tool_calls handles multiple Responses-style dict-shaped tool calls."""

    response = type(
        "Response",
        (),
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "text",
                            "text": "I should check the weather before answering.",
                        }
                    ],
                },
                {
                    "type": "function_call",
                    "name": "get_current_weather",
                    "arguments": '{"location": "San Diego, CA", "unit": "F"}',
                    "call_id": "call_456",
                },
                {
                    "type": "function_call",
                    "name": "get_current_weather",
                    "arguments": '{"location": "New York, NY", "unit": "F"}',
                    "call_id": "call_789",
                },
            ],
        },
    )()

    tool_calls = extract_tool_calls(response.output)

    assert isinstance(tool_calls, list)
    assert len(tool_calls) == 2
    assert tool_calls[0].tool_name == "get_current_weather"
    assert tool_calls[0].arguments == {"location": "San Diego, CA", "unit": "F"}
    assert tool_calls[0].call_id == "call_456"
    assert tool_calls[1].tool_name == "get_current_weather"
    assert tool_calls[1].arguments == {"location": "New York, NY", "unit": "F"}
    assert tool_calls[1].call_id == "call_789"


def test_tool_helpers_normalize_and_wrap_output() -> None:
    """Verify parsing and output helpers produce stable shapes."""

    assert normalize_tool_arguments('{"location": "San Diego, CA"}') == {"location": "San Diego, CA"}
    payload = build_tool_call_output(
        "call_123",
        type("Result", (), {"success": True, "output": "ok", "error": ""})(),
    )
    assert payload["call_id"] == "call_123"
    assert payload["output"] == "ok"
    assert "id" not in payload


def test_tool_service_supports_direct_tool_call_and_result_inputs() -> None:
    """Verify the tool service helpers still work with direct ToolCall and ToolResult inputs."""

    registry = ToolRegistry()
    service = ToolService(registry)
    definition = build_weather_tool_definition()

    assert service.register_tool(definition, get_current_weather) is True

    tool_call = type(
        "ToolCall",
        (),
        {
            "tool_name": "get_current_weather",
            "arguments": {"location": "San Diego, CA", "unit": "F"},
            "call_id": "call_123",
        },
    )()

    tool_result = service.execute(tool_call.tool_name, tool_call.arguments)
    assert tool_result.success is True
    assert tool_result.output == "The weather in San Diego, CA is 12F and cold."

    tool_output = build_tool_call_output(tool_call.call_id, tool_result)
    assert tool_output["call_id"] == "call_123"
    assert tool_output["output"] == "The weather in San Diego, CA is 12F and cold."
    assert "id" not in tool_output


def test_tool_service_builds_follow_up_payload_from_direct_tool_result() -> None:
    """Verify follow-up payload building from a direct ToolResult input."""

    tool_result = type(
        "ToolResult",
        (),
        {
            "success": True,
            "output": "The weather in San Diego, CA is 12F and cold.",
            "error": "",
        },
    )()

    payload = build_tool_call_output("call_123", tool_result)

    assert payload["call_id"] == "call_123"
    assert payload["output"] == "The weather in San Diego, CA is 12F and cold."
    assert "id" not in payload
