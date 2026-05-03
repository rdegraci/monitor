"""Tests for ToolCallHandler."""
from __future__ import annotations

from monitor_oop.core.tools.tool_call_handler import ToolCallHandler
from monitor_oop.core.tools.tool_models import ToolCall, ToolResult


class RecordingToolService:
    """Minimal tool service stub for ToolCallHandler tests."""

    def __init__(self, results: list[ToolResult] | None = None) -> None:
        self.results = list(results or [])
        self.executed_calls: list[ToolCall] = []
        self.follow_up_payloads: list[dict[str, object]] = []
        self.follow_up_payloads_multi: list[tuple[list[dict[str, str]], list[tuple[str, str, ToolResult]], str | None]] = []

    def execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
        """Record the tool call and return the next configured result."""

        self.executed_calls.append(tool_call)
        if not self.results:
            return ToolResult(tool_name=tool_call.tool_name, success=True, output="done")
        return self.results.pop(0)

    def build_follow_up_payload(
        self,
        messages: list[dict[str, str]],
        call_id: str,
        response_item_id: str,
        result: ToolResult,
    ) -> list[dict[str, str]]:
        """Record single-tool follow-up payload construction."""

        self.follow_up_payloads.append(
            {
                "messages": messages,
                "call_id": call_id,
                "response_item_id": response_item_id,
                "result": result,
            }
        )
        return messages

    def build_follow_up_payloads(
        self,
        messages: list[dict[str, str]],
        tool_results: list[tuple[str, str, ToolResult]],
        parent_response_id: str | None = None,
    ) -> list[dict[str, str]]:
        """Record multi-tool follow-up payload construction."""

        self.follow_up_payloads_multi.append((messages, tool_results, parent_response_id))
        return messages


def build_tool_call(
    call_id: str,
    tool_name: str,
    arguments: dict[str, object],
    response_item_id: str | None = None,
) -> ToolCall:
    """Build a deterministic tool call for tests."""

    return ToolCall(
        call_id=call_id,
        response_item_id=response_item_id,
        tool_name=tool_name,
        arguments=arguments,
    )


def build_response(
    response_id: str,
    tool_calls: list[dict[str, object]] | None = None,
    finish_reason: str = "tool_calls",
) -> object:
    """Build a minimal fake model response."""

    response = type("Response", (), {})()
    response.id = response_id
    response.finish_reason = finish_reason
    response.output = tool_calls or []
    return response


def test_execute_tool_calls_single_call_records_follow_up_payload() -> None:
    """Verify a single tool call is executed and tracked."""

    tool_service = RecordingToolService(results=[ToolResult(tool_name="get_current_weather", success=True, output="sunny")])
    handler = ToolCallHandler(tool_service=tool_service)
    response = build_response(
        response_id="response_1",
        tool_calls=[
            {
                "type": "function_call",
                "id": "call_1",
                "call_id": "call_1",
                "name": "get_current_weather",
                "arguments": {"location": "San Diego, CA", "unit": "F"},
            }
        ],
    )
    input_messages = [{"role": "user", "content": "hello"}]

    next_messages, should_continue = handler.execute_tool_calls(input_messages, response)

    assert should_continue is True
    assert next_messages == input_messages
    assert len(tool_service.executed_calls) == 1
    assert len(tool_service.follow_up_payloads) == 0
    assert len(tool_service.follow_up_payloads_multi) == 1


def test_execute_tool_calls_multiple_calls_preserves_order() -> None:
    """Verify multiple tool calls execute in order and preserve follow-up sequencing."""

    tool_service = RecordingToolService(
        results=[
            ToolResult(tool_name="get_current_weather", success=True, output="sunny"),
            ToolResult(tool_name="get_current_weather", success=True, output="rainy"),
        ]
    )
    handler = ToolCallHandler(tool_service=tool_service)
    response = build_response(
        response_id="response_1",
        tool_calls=[
            {
                "type": "function_call",
                "id": "call_1",
                "call_id": "call_1",
                "name": "get_current_weather",
                "arguments": {"location": "San Diego, CA", "unit": "F"},
            },
            {
                "type": "function_call",
                "id": "call_2",
                "call_id": "call_2",
                "name": "get_current_weather",
                "arguments": {"location": "Portland, OR", "unit": "C"},
            },
        ],
    )
    input_messages = [{"role": "user", "content": "hello"}]

    next_messages, should_continue = handler.execute_tool_calls(input_messages, response)

    assert should_continue is True
    assert next_messages == input_messages
    assert [call.call_id for call in tool_service.executed_calls] == ["call_1", "call_2"]
    assert len(tool_service.follow_up_payloads_multi) == 1
    follow_up_messages, tool_results, parent_response_id = tool_service.follow_up_payloads_multi[0]
    assert follow_up_messages == input_messages
    assert parent_response_id == "response_1"
    assert tool_results[0][0] == "call_1"
    assert tool_results[1][0] == "call_2"


def test_execute_tool_calls_without_calls_returns_false() -> None:
    """Verify no tool calls produces no continuation."""

    tool_service = RecordingToolService()
    handler = ToolCallHandler(tool_service=tool_service)
    response = build_response(response_id="response_1", tool_calls=[], finish_reason="stop")
    input_messages = [{"role": "user", "content": "hello"}]

    next_messages, should_continue = handler.execute_tool_calls(input_messages, response)

    assert should_continue is False
    assert next_messages == input_messages
    assert tool_service.executed_calls == []


def test_tool_turn_state_does_not_leak_between_calls() -> None:
    """Verify tool turn state is reset when no tool calls are present."""

    tool_service = RecordingToolService()
    handler = ToolCallHandler(tool_service=tool_service)

    first_response = build_response(
        response_id="response_1",
        tool_calls=[
            {
                "type": "function_call",
                "id": "call_1",
                "call_id": "call_1",
                "name": "get_current_weather",
                "arguments": {"location": "San Diego, CA", "unit": "F"},
            }
        ],
    )
    second_response = build_response(response_id="response_2", tool_calls=[], finish_reason="stop")
    input_messages = [{"role": "user", "content": "hello"}]

    first_next_messages, first_should_continue = handler.execute_tool_calls(input_messages, first_response)
    second_next_messages, second_should_continue = handler.execute_tool_calls(first_next_messages, second_response)

    assert first_should_continue is True
    assert first_next_messages == input_messages
    assert second_should_continue is False
    assert second_next_messages == input_messages
    assert len(tool_service.executed_calls) == 1
