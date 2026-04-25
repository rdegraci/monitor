"""Tests for LLMService tool-loop behavior."""
from __future__ import annotations

import pytest

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.llm_service import LLMService
from monitor_oop.core.tools.tool_models import ToolCall, ToolResult
from monitor_oop.core.tools.registry import ToolRegistry
from monitor_oop.core.tools.tool_service import ToolService
from monitor_oop.core.tools.weather import build_weather_tool_definition, get_current_weather


class FakeAdapter:
    """Minimal adapter stub for LLMService tests."""

    def __init__(self, responses: list[object], texts: list[str]) -> None:
        self.responses = list(responses)
        self.texts = list(texts)
        self.complete_calls: list[tuple[str, list[dict[str, str]], str, list[dict[str, object]] | None, str | None]] = []

    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        api_key: str,
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | None = None,
    ) -> object:
        """Return the next queued response and record the call."""

        self.complete_calls.append((model, messages, api_key, tools, tool_choice))
        return self.responses.pop(0)

    def extract_text(self, response: object) -> str:
        """Return the next queued assistant text."""

        if self.texts:
            return self.texts.pop(0)
        return ""


class FakeToolService:
    """Minimal tool service stub for LLMService tests."""

    def __init__(self, tool_call: ToolCall | None = None, result: ToolResult | None = None) -> None:
        self.tool_call = tool_call
        self.result = result or ToolResult(tool_name="get_current_weather", success=True, output="done")
        self.executed_calls: list[ToolCall] = []
        self.follow_up_payloads: list[tuple[list[dict[str, str]], str, ToolResult]] = []

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

    def parse_tool_call(self, value: object) -> ToolCall | None:
        """Return the configured tool call."""

        return self.tool_call

    def execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
        """Record the tool call and return the configured result."""

        self.executed_calls.append(tool_call)
        return self.result

    def build_follow_up_payload(
        self,
        messages: list[dict[str, str]],
        call_id: str,
        result: ToolResult,
    ) -> list[dict[str, str]]:
        """Record the payload construction and return the original messages."""

        self.follow_up_payloads.append((messages, call_id, result))
        return messages


def build_response(finish_reason: str | None, output_text: str = "assistant text") -> object:
    """Build a minimal fake response object."""

    response = type("Response", (), {})()
    response.finish_reason = finish_reason
    response.output_text = output_text
    return response


def build_service(
    responses: list[object],
    texts: list[str],
    tool_service: FakeToolService | None = None,
) -> tuple[LLMService, FakeAdapter, FakeToolService | None]:
    """Build an LLMService with faked adapter behavior."""

    config_service = ConfigService()
    config_service.get_openai_api_key = lambda: "test-key"  # type: ignore[method-assign]
    config_service.get_model = lambda: "openai/gpt-4o-mini"  # type: ignore[method-assign]
    service = LLMService(config_service, tool_service=tool_service)
    fake_adapter = FakeAdapter(responses, texts)
    service.adapter = fake_adapter
    return service, fake_adapter, tool_service


def test_complete_returns_text_for_stop_response() -> None:
    """Verify stop responses return assistant text without tool execution."""

    service, adapter, _ = build_service([build_response("stop")], ["final answer"])

    result = service.complete("hello", [])

    assert result == "final answer"
    assert len(adapter.complete_calls) == 1


def test_complete_executes_tool_call_and_returns_final_text() -> None:
    """Verify tool calls trigger execution and a follow-up model response."""

    tool_call = ToolCall(call_id="call_1", tool_name="get_current_weather", arguments={"location": "San Diego, CA", "unit": "F"})
    tool_service = FakeToolService(tool_call=tool_call, result=ToolResult(tool_name="get_current_weather", success=True, output="weather done"))
    service, adapter, fake_tool_service = build_service(
        [build_response("tool_calls"), build_response("stop")],
        ["final answer"],
        tool_service=tool_service,
    )

    result = service.complete("hello", [])

    assert result == "final answer"
    assert len(adapter.complete_calls) == 2
    assert fake_tool_service is not None
    assert len(fake_tool_service.executed_calls) == 1
    assert fake_tool_service.executed_calls[0].tool_name == "get_current_weather"
    assert len(fake_tool_service.follow_up_payloads) == 1
    assert fake_tool_service.follow_up_payloads[0][1] == "call_1"


def test_complete_raises_for_malformed_tool_call() -> None:
    """Verify malformed tool-call responses raise a clear error."""

    tool_service = FakeToolService(tool_call=None)
    service, _, _ = build_service([build_response("tool_calls")], ["final answer"], tool_service=tool_service)

    with pytest.raises(ValueError, match="malformed"):
        service.complete("hello", [])


def test_complete_raises_for_content_filter_response() -> None:
    """Verify filtered responses raise a clear error."""

    service, _, _ = build_service([build_response("content_filter")], ["final answer"])

    with pytest.raises(ValueError, match="filtered"):
        service.complete("hello", [])


def test_complete_raises_for_length_response() -> None:
    """Verify length-limited responses raise a clear error."""

    service, _, _ = build_service([build_response("length")], ["final answer"])

    with pytest.raises(ValueError, match="length limit"):
        service.complete("hello", [])


def test_complete_returns_text_when_finish_reason_is_none() -> None:
    """Verify responses with no finish reason are handled conservatively."""

    service, adapter, _ = build_service([build_response(None)], ["final answer"])

    result = service.complete("hello", [])

    assert result == "final answer"
    assert len(adapter.complete_calls) == 1


class LoopingFakeToolService:
    """Tool service stub that always produces a valid tool call."""

    def __init__(self) -> None:
        self.executed_calls: list[ToolCall] = []
        self.follow_up_payloads: list[tuple[list[dict[str, str]], str, ToolResult]] = []
        self._tool_call = ToolCall(
            call_id="call_1",
            tool_name="get_current_weather",
            arguments={"location": "San Diego, CA", "unit": "F"},
        )
        self._result = ToolResult(tool_name="get_current_weather", success=True, output="done")

    def build_litellm_tools(self) -> list[dict[str, object]]:
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

    def parse_tool_call(self, value: object) -> ToolCall | None:
        return self._tool_call

    def execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
        self.executed_calls.append(tool_call)
        return self._result

    def build_follow_up_payload(
        self,
        messages: list[dict[str, str]],
        call_id: str,
        result: ToolResult,
    ) -> list[dict[str, str]]:
        self.follow_up_payloads.append((messages, call_id, result))
        return messages


class LoopingFakeAdapter:
    """Adapter stub that repeatedly returns tool-call responses."""

    def __init__(self) -> None:
        self.complete_calls: list[tuple[str, list[dict[str, str]], str, list[dict[str, object]] | None, str | None]] = []

    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        api_key: str,
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | None = None,
    ) -> object:
        self.complete_calls.append((model, messages, api_key, tools, tool_choice))
        return build_response("tool_calls")

    def extract_text(self, response: object) -> str:
        return "assistant text"


class RecordingAdapter:
    """Adapter stub that records keyword arguments passed to complete."""

    def __init__(self) -> None:
        self.complete_calls: list[dict[str, object]] = []

    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        api_key: str,
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | None = None,
    ) -> object:
        self.complete_calls.append(
            {
                "model": model,
                "messages": messages,
                "api_key": api_key,
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        return build_response("stop")

    def extract_text(self, response: object) -> str:
        return "final answer"


def test_create_response_passes_litellm_tools_and_auto_choice() -> None:
    """Verify tool schemas are forwarded to the adapter when creating a response."""

    config_service = ConfigService()
    config_service.get_openai_api_key = lambda: "test-key"  # type: ignore[method-assign]
    config_service.get_model = lambda: "openai/gpt-4o-mini"  # type: ignore[method-assign]

    tool_registry = ToolRegistry()
    tool_registry.register(build_weather_tool_definition(), get_current_weather)
    tool_service = ToolService(tool_registry)
    service = LLMService(config_service, tool_service=tool_service)
    adapter = RecordingAdapter()
    service.adapter = adapter

    service.create_response([{"role": "user", "content": "hello"}])

    assert len(adapter.complete_calls) == 1
    call = adapter.complete_calls[0]
    assert call["tool_choice"] == "auto"
    assert "tools" in call
    assert isinstance(call["tools"], list)
    assert len(call["tools"]) >= 1
    assert any(
        isinstance(tool, dict)
        and (
            tool.get("function", {}).get("name") == "get_current_weather"
            or tool.get("name") == "get_current_weather"
        )
        for tool in call["tools"]
    )


def test_complete_enforces_max_tool_loop_iterations() -> None:
    """Verify the defensive tool-loop cap prevents infinite retries."""

    config_service = ConfigService()
    config_service.get_openai_api_key = lambda: "test-key"  # type: ignore[method-assign]
    config_service.get_model = lambda: "openai/gpt-4o-mini"  # type: ignore[method-assign]

    tool_service = LoopingFakeToolService()
    service = LLMService(config_service, tool_service=tool_service)
    adapter = LoopingFakeAdapter()
    service.adapter = adapter

    with pytest.raises(RuntimeError, match="maximum.*5"):
        service.complete("hello", [])

    assert len(adapter.complete_calls) == 5
    assert len(tool_service.executed_calls) == 5
