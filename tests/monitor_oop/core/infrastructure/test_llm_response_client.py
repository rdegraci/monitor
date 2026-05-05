"""Tests for LLMResponseClient."""
from __future__ import annotations

import pytest

import monitor_oop.core.infrastructure.llm_response_client as llm_response_client_module
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.infrastructure.llm_response_client import LLMResponseClient
from monitor_oop.core.tools.tool_models import ToolDefinition


class FakeAdapter:
    """Minimal adapter stub for response client tests."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        api_key: str,
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | None = None,
        previous_response_id: str | None = None,
    ) -> object:
        """Record the call and return a sentinel response."""

        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "api_key": api_key,
                "tools": tools,
                "tool_choice": tool_choice,
                "previous_response_id": previous_response_id,
            }
        )
        return {"ok": True}


class FakeToolService:
    """Minimal tool service stub for response client tests."""

    def __init__(self) -> None:
        self.called = False

    def build_responses_tools(self) -> list[dict[str, object]]:
        """Return a stable tool schema for tests."""

        self.called = True
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_current_weather",
                    "description": "Get the current weather for a location.",
                    "parameters": {"type": "object"},
                },
            }
        ]


def test_create_response_requires_api_key(monkeypatch) -> None:
    """Verify the client fails clearly when the API key is missing."""

    config_service = ConfigService()
    config_service.get_openai_api_key = lambda: None  # type: ignore[method-assign]
    client = LLMResponseClient(config_service)

    with pytest.raises(ValueError, match="API key"):
        client.create_response([{"role": "user", "content": "hello"}])


def test_create_response_normalizes_model_and_passes_tools(monkeypatch) -> None:
    """Verify model normalization and tool schema wiring for the adapter boundary."""

    fake_adapter = FakeAdapter()
    monkeypatch.setattr(llm_response_client_module, "ResponsesAdapter", lambda: fake_adapter)

    config_service = ConfigService()
    config_service.get_openai_api_key = lambda: "test-key"  # type: ignore[method-assign]
    config_service.get_model = lambda: "openai/gpt-4o-mini"  # type: ignore[method-assign]

    tool_service = FakeToolService()
    client = LLMResponseClient(config_service, tool_service=tool_service)

    response = client.create_response(
        [{"role": "user", "content": "hello"}],
        previous_response_id="response_1",
    )

    assert response == {"ok": True}
    assert tool_service.called is True
    assert len(fake_adapter.calls) == 1
    call = fake_adapter.calls[0]
    assert call["model"] == "gpt-4o-mini"
    assert call["api_key"] == "test-key"
    assert call["messages"] == [{"role": "user", "content": "hello"}]
    assert call["previous_response_id"] == "response_1"
    assert isinstance(call["tools"], list)
    assert len(call["tools"]) == 1
    tool_schema = call["tools"][0]
    assert isinstance(tool_schema, dict)
    assert tool_schema["type"] == "function"
    function_schema = tool_schema["function"]
    assert function_schema["name"] == "get_current_weather"


def test_create_response_uses_unprefixed_model_unchanged(monkeypatch) -> None:
    """Verify unprefixed model names are passed through unchanged."""

    fake_adapter = FakeAdapter()
    monkeypatch.setattr(llm_response_client_module, "ResponsesAdapter", lambda: fake_adapter)

    config_service = ConfigService()
    config_service.get_openai_api_key = lambda: "test-key"  # type: ignore[method-assign]
    config_service.get_model = lambda: "gpt-4o-mini"  # type: ignore[method-assign]

    client = LLMResponseClient(config_service)

    client.create_response([{"role": "user", "content": "hello"}])

    assert len(fake_adapter.calls) == 1
    assert fake_adapter.calls[0]["model"] == "gpt-4o-mini"
