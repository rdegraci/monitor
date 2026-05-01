"""Tests for the isolated Monitor OOP tool subsystem."""
from monitor_oop.core.tools import (
    ToolRegistry,
    ToolService,
    build_tool_call_output,
    build_weather_tool_definition,
    extract_tool_calls,
    get_current_weather,
    normalize_tool_arguments,
)


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
