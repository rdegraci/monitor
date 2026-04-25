"""Tests for the isolated Monitor OOP tool subsystem."""
from monitor_oop.core.tools import (
    ToolRegistry,
    ToolService,
    build_tool_call_output,
    build_weather_tool_definition,
    get_current_weather,
    normalize_tool_arguments,
    parse_tool_call,
    should_continue_after_tool_call,
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


def test_tool_helpers_normalize_and_wrap_output() -> None:
    """Verify parsing and output helpers produce stable shapes."""

    assert normalize_tool_arguments('{"location": "San Diego, CA"}') == {"location": "San Diego, CA"}
    payload = build_tool_call_output(
        "call_123",
        type("Result", (), {"success": True, "output": "ok", "error": ""})(),
    )
    assert payload["call_id"] == "call_123"
    assert payload["output"] == "ok"
    assert should_continue_after_tool_call(type("Response", (), {"output": []})()) is False
    assert parse_tool_call(type("Response", (), {"output": []})()) is None


def test_tool_service_supports_multi_round_tool_loop() -> None:
    """Verify a tool loop can be driven by stubbed assistant responses."""

    registry = ToolRegistry()
    service = ToolService(registry)
    definition = build_weather_tool_definition()

    assert service.register_tool(definition, get_current_weather) is True

    first_response = type(
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

    assert should_continue_after_tool_call(first_response) is True
    tool_call = parse_tool_call(first_response)
    assert tool_call is not None
    assert tool_call.tool_name == "get_current_weather"
    assert tool_call.arguments == {"location": "San Diego, CA", "unit": "F"}

    tool_result = service.execute(tool_call.tool_name, tool_call.arguments)
    tool_output = build_tool_call_output(tool_call.call_id, tool_result)
    assert tool_output["call_id"] == "call_123"
    assert tool_output["output"] == "The weather in San Diego, CA is 12F and cold."

    follow_up_response = type(
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
                                    "text": "The weather in San Diego, CA is 12F and cold.",
                                },
                            )()
                        ],
                    },
                )(),
            ],
        },
    )()

    assert should_continue_after_tool_call(follow_up_response) is False
    assert parse_tool_call(follow_up_response) is None
