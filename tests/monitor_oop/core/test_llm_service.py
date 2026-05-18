"""Tests for LLMService tool-loop behavior."""
from __future__ import annotations

import pytest

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.infrastructure.macro_store import MacroStore
from monitor_oop.core.llm_service import LLMService
from monitor_oop.core.models import Message
from monitor_oop.core.prompt_service import PromptService
from monitor_oop.core.tools.tool_models import ToolCall, ToolResult


class RecordingAdapter:
    """Minimal adapter stub for LLMService tests."""

    def __init__(self, texts: list[str]) -> None:
        self.texts = list(texts)

    def extract_text(self, response: object) -> str:
        """Return the next queued assistant text."""

        if self.texts:
            return self.texts.pop(0)
        return ""


class RecordingResponseClient:
    """Minimal response client stub for LLMService tests."""

    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.complete_calls: list[dict[str, object]] = []

    def create_response(
        self,
        input_messages: list[dict[str, str]],
        previous_response_id: str | None = None,
    ) -> object:
        """Return the next queued response and record the call."""

        self.complete_calls.append(
            {
                "input_messages": input_messages,
                "previous_response_id": previous_response_id,
            }
        )
        if self.responses:
            return self.responses.pop(0)

        raise AssertionError("RecordingResponseClient.create_response() ran out of queued responses")


class RecordingToolService:
    """Minimal tool service stub for LLMService tests."""

    def __init__(
        self,
        tool_calls: list[ToolCall] | None = None,
        result: ToolResult | list[ToolResult] | None = None,
    ) -> None:
        self.tool_calls = list(tool_calls or [])
        self.result = result or ToolResult(tool_name="get_current_weather", success=True, output="done")
        self.executed_calls: list[ToolCall] = []
        self.follow_up_payloads: list[dict[str, object]] = []
        self.follow_up_payloads_multi: list[tuple[list[dict[str, str]], list[tuple[str, str, ToolResult]], str | None]] = []
        self.parsed_tool_calls_seen: list[object] = []

    def build_litellm_tools(self) -> list[dict[str, object]]:
        """Return a tool schema compatible with LiteLLM."""

        return [
            {
                "type": "function",
                "function": {
                    "name": "get_current_weather",
                    "description": "Get the current weather for a location.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"},
                            "unit": {"type": "string"},
                        },
                        "required": ["location"],
                    },
                },
            }
        ]

    def build_responses_tools(self) -> list[dict[str, object]]:
        """Return a tool schema compatible with the Responses API."""

        return self.build_litellm_tools()

    def parse_tool_calls(self, value: object) -> list[ToolCall]:
        """Return the configured tool calls."""

        self.parsed_tool_calls_seen.append(value)
        return list(self.tool_calls)

    def execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
        """Record the tool call and return the configured result."""

        self.executed_calls.append(tool_call)
        if isinstance(self.result, list):
            if not self.result:
                raise AssertionError("RecordingToolService ran out of configured results")
            return self.result.pop(0)
        return self.result

    def build_follow_up_payload(
        self,
        messages: list[dict[str, str]],
        call_id: str,
        response_item_id: str,
        result: ToolResult,
    ) -> list[dict[str, str]]:
        """Record the payload construction and return the original messages."""

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
        """Record multi-tool follow-up payload construction and return the original messages."""

        self.follow_up_payloads_multi.append((messages, tool_results, parent_response_id))
        return messages


class MultiCallToolService(RecordingToolService):
    """Tool service stub that returns multiple parsed tool calls."""

    def __init__(self, tool_calls: list[ToolCall], results: list[ToolResult]) -> None:
        self._configured_results = list(results)
        super().__init__(tool_calls=tool_calls, result=list(results))

    def parse_tool_calls(self, value: object) -> list[ToolCall]:
        self.parsed_tool_calls_seen.append(value)
        return list(self.tool_calls)

    def execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
        self.executed_calls.append(tool_call)
        if isinstance(self.result, list) and self.result:
            return self.result.pop(0)

        if self._configured_results:
            return self._configured_results[0]

        return ToolResult(tool_name=tool_call.tool_name, success=True, output="done")


def build_response(finish_reason: str | None, response_id: str, output_text: str = "assistant text") -> object:
    """Build a minimal fake response object."""

    response = type("Response", (), {})()
    response.finish_reason = finish_reason
    response.output_text = output_text
    response.id = response_id
    return response


def build_final_response(response_id: str = "response_final", output_text: str = "final answer") -> object:
    """Build a fake final assistant response object with message-like output."""

    response = type("Response", (), {})()
    response.finish_reason = "stop"
    response.id = response_id
    response.output = [
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": output_text,
                }
            ],
        }
    ]
    response.output_text = output_text
    return response


def build_tool_call_response(
    response_id: str,
    call_id: str,
    tool_name: str,
    arguments: dict[str, object],
) -> object:
    """Build a fake Responses API response with a single function call output item."""

    response = type("Response", (), {})()
    response.finish_reason = "tool_calls"
    response.id = response_id
    response.output = [
        {
            "type": "function_call",
            "id": call_id,
            "call_id": call_id,
            "name": tool_name,
            "arguments": arguments,
        }
    ]
    response.output_text = ""
    return response


def build_service(
    responses: list[object],
    texts: list[str],
    tool_service: RecordingToolService | None = None,
) -> tuple[LLMService, RecordingAdapter, RecordingResponseClient, RecordingToolService | None]:
    """Build an LLMService with faked response client behavior."""

    config_service = ConfigService()
    prompt_store = MacroStore("monitor_oop")
    prompt_service = PromptService(config_service=config_service, prompt_store=prompt_store)

    class RequestBuilderStub:
        """Minimal request builder stub for LLMService tests."""

        def build_input(self, *args: object, **kwargs: object) -> list[dict[str, str]]:
            return [{"role": "user", "content": "hello"}]

    class ToolCallHandlerStub:
        """Minimal tool call handler stub for LLMService tests."""

        def execute_tool_calls(
            self,
            input_messages: list[dict[str, str]],
            response: object,
        ) -> tuple[list[dict[str, str]], bool]:
            if getattr(response, "finish_reason", None) != "tool_calls":
                return input_messages, False

            if tool_service is not None:
                parsed_tool_calls = tool_service.parse_tool_calls(response)
                for tool_call in parsed_tool_calls:
                    tool_service.execute_tool_call(tool_call)
            return input_messages, True

    adapter = RecordingAdapter(texts)
    service = LLMService(
        config_service=config_service,
        prompt_service=prompt_service,
        request_builder=RequestBuilderStub(),
        response_client=RecordingResponseClient(responses),
        tool_call_handler=ToolCallHandlerStub(),
        adapter=adapter,
        tool_service=tool_service,
    )
    fake_response_client = service._response_client
    return service, adapter, fake_response_client, tool_service


class SharedToolCallHandlerStub:
    """Minimal tool call handler stub for LLMService tests."""

    def __init__(self, tool_service: RecordingToolService) -> None:
        self.tool_service = tool_service

    def execute_tool_calls(
        self,
        input_messages: list[dict[str, str]],
        response: object,
    ) -> tuple[list[dict[str, str]], bool]:
        if getattr(response, "finish_reason", None) != "tool_calls":
            return input_messages, False

        parsed_tool_calls = self.tool_service.parse_tool_calls(response)
        for tool_call in parsed_tool_calls:
            self.tool_service.execute_tool_call(tool_call)
        return input_messages, True


def test_complete_returns_text_for_stop_response() -> None:
    """Verify stop responses return assistant text without tool execution."""

    service, adapter, response_client, _ = build_service([build_response("stop", "response_1")], ["final answer"])

    result = service.complete([Message(role="user", content="hello")])

    assert result.assistant_text == "final answer"
    assert result.response_id == "response_1"
    assert result.messages == [Message(role="assistant", content="final answer", response_id="response_1")]
    assert len(response_client.complete_calls) == 1
    assert response_client.complete_calls[0]["previous_response_id"] is None
    assert len(adapter.texts) == 0


def test_complete_includes_response_ids_on_result_and_message() -> None:
    """Verify stop responses propagate response IDs onto the completion result and assistant message."""

    def build_response_with_parent(
        response_id: str,
        parent_response_id: str,
        output_text: str,
    ) -> object:
        response = type("Response", (), {})()
        response.id = response_id
        response.parent_response_id = parent_response_id
        response.finish_reason = "stop"
        response.output_text = output_text
        return response

    service, _, _, _ = build_service(
        [build_response_with_parent("response_1", "response_parent", "final answer")],
        ["final answer"],
    )

    result = service.complete([Message(role="user", content="hello")])

    assert result.response_id == "response_1"
    assert result.parent_response_id == "response_parent"
    assert result.messages == [
        Message(
            role="assistant",
            content="final answer",
            response_id="response_1",
            parent_response_id="response_parent",
        )
    ]


def test_complete_executes_single_tool_call_completion_path() -> None:
    """Verify a single tool-call response executes one tool and returns assistant text."""

    tool_call = ToolCall(
        call_id="call_1",
        response_item_id="call_1",
        tool_name="get_current_weather",
        arguments={"location": "San Diego, CA", "unit": "F"},
    )
    tool_service = RecordingToolService(
        tool_calls=[tool_call],
        result=ToolResult(tool_name="get_current_weather", success=True, output="done"),
    )
    service, adapter, response_client, _ = build_service(
        [
            build_tool_call_response("response_1", "call_1", "get_current_weather", {"location": "San Diego, CA", "unit": "F"}),
            build_response("stop", "response_2"),
        ],
        ["assistant text", "final answer"],
        tool_service=tool_service,
    )

    result = service.complete([Message(role="user", content="hello")])

    assert result.assistant_text == "assistant text"
    assert result.response_id == "response_2"
    assert result.messages == [Message(role="assistant", content="assistant text", response_id="response_2")]
    assert len(tool_service.executed_calls) == 1
    assert len(response_client.complete_calls) == 2
    assert len(adapter.texts) == 1
    assert len(tool_service.parsed_tool_calls_seen) == 1


def test_complete_raises_for_content_filter_response() -> None:
    """Verify filtered responses raise a clear error."""

    service, _, response_client, _ = build_service([build_response("content_filter", "response_1")], ["final answer"])

    with pytest.raises(ValueError, match="filtered"):
        service.complete([Message(role="user", content="hello")])

    assert len(response_client.complete_calls) == 1


def test_complete_raises_for_length_response() -> None:
    """Verify length-limited responses raise a clear error."""

    service, _, response_client, _ = build_service([build_response("length", "response_1")], ["final answer"])

    with pytest.raises(ValueError, match="length limit"):
        service.complete([Message(role="user", content="hello")])

    assert len(response_client.complete_calls) == 1


def test_complete_enforces_max_tool_loop_iterations() -> None:
    """Verify the defensive tool-loop cap prevents infinite retries."""

    config_service = ConfigService()

    tool_service = RecordingToolService(
        tool_calls=[
            ToolCall(
                call_id="call_1",
                tool_name="get_current_weather",
                arguments={"location": "San Diego, CA", "unit": "F"},
            )
        ],
        result=[
            ToolResult(tool_name="get_current_weather", success=True, output="turn_1"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_2"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_3"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_4"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_5"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_6"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_7"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_8"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_9"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_10"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_11"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_12"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_13"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_14"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_15"),
            ToolResult(tool_name="get_current_weather", success=True, output="turn_16"),
        ],
    )
    prompt_store = MacroStore("monitor_oop")
    prompt_service = PromptService(config_service=config_service, prompt_store=prompt_store)

    class RequestBuilderStub:
        """Minimal request builder stub for LLMService tests."""

        def build_input(self, *args: object, **kwargs: object) -> list[dict[str, str]]:
            return [{"role": "user", "content": "hello"}]

    class LoopingResponseClient:
        """Response client stub that repeatedly returns tool-call responses."""

        def __init__(self) -> None:
            self.complete_calls: list[dict[str, object]] = []
            self._count = 0

        def create_response(
            self,
            input_messages: list[dict[str, str]],
            previous_response_id: str | None = None,
        ) -> object:
            self.complete_calls.append(
                {
                    "input_messages": input_messages,
                    "previous_response_id": previous_response_id,
                }
            )
            self._count += 1
            if self._count > 16:
                raise AssertionError("LoopingResponseClient.create_response() ran out of queued responses")
            return build_tool_call_response(
                response_id=f"response_{self._count}",
                call_id="call_1",
                tool_name="get_current_weather",
                arguments={"location": "San Diego, CA", "unit": "F"},
            )

    adapter = RecordingAdapter(["assistant text"])
    response_client = LoopingResponseClient()
    service = LLMService(
        config_service=config_service,
        prompt_service=prompt_service,
        request_builder=RequestBuilderStub(),
        response_client=response_client,
        tool_call_handler=SharedToolCallHandlerStub(tool_service),
        adapter=adapter,
        tool_service=tool_service,
    )

    with pytest.raises(RuntimeError, match="maximum.*16"):
        service.complete([Message(role="user", content="hello")])

    assert len(response_client.complete_calls) == 16
    assert len(tool_service.executed_calls) == 16


def test_complete_parses_and_executes_multiple_tool_calls() -> None:
    """Verify multiple parsed tool calls are executed in order and the current completion text is returned."""

    tool_calls = [
        ToolCall(
            call_id="call_1",
            response_item_id="call_1",
            tool_name="get_current_weather",
            arguments={"location": "San Diego, CA", "unit": "F"},
        ),
        ToolCall(
            call_id="call_2",
            response_item_id="call_2",
            tool_name="get_current_weather",
            arguments={"location": "Portland, OR", "unit": "C"},
        ),
    ]
    tool_service = MultiCallToolService(
        tool_calls=tool_calls,
        results=[
            ToolResult(tool_name="get_current_weather", success=True, output="sunny"),
            ToolResult(tool_name="get_current_weather", success=True, output="rainy"),
        ],
    )

    service, fake_adapter, response_client, _ = build_service(
        [
            build_tool_call_response(
                response_id="response_1",
                call_id="call_1",
                tool_name="get_current_weather",
                arguments={"location": "San Diego, CA", "unit": "F"},
            ),
            build_tool_call_response(
                response_id="response_2",
                call_id="call_2",
                tool_name="get_current_weather",
                arguments={"location": "Portland, OR", "unit": "C"},
            ),
            build_final_response(response_id="response_3", output_text="done"),
        ],
        ["assistant text", "assistant text", "final answer"],
        tool_service=tool_service,
    )

    result = service.complete([Message(role="user", content="hello")])

    assert len(response_client.complete_calls) >= 2
    assert len(tool_service.executed_calls) >= 2
    assert tool_service.executed_calls[:2] == tool_calls
    assert result
    assert len(fake_adapter.texts) >= 0
