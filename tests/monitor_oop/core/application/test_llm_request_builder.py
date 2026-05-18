"""Tests for LLMRequestBuilder."""
from monitor_oop.core.application.llm_request_builder import LLMRequestBuilder
from monitor_oop.core.models import Message


def test_build_input_renders_history_without_appending_user_input() -> None:
    """Verify request input is rendered from history alone, with no trailing append."""

    builder = LLMRequestBuilder()
    history = [
        Message(role="system", content="system note"),
        "prior user text",
        Message(role="assistant", content="assistant reply"),
        Message(role="user", content="current user text"),
    ]

    result = builder.build_input(history)

    assert result == [
        {"role": "system", "content": "system note"},
        {"role": "user", "content": "prior user text"},
        {"role": "assistant", "content": "assistant reply"},
        {"role": "user", "content": "current user text"},
    ]


def test_build_input_preserves_tool_call_metadata_on_assistant_and_tool_messages() -> None:
    """Verify tool_calls / tool_call_id / name survive serialization to the request.

    The boundary tracker preserves tool clusters during compaction, but a prior
    bug in this builder silently dropped tool_calls/tool_call_id when rendering
    the request — so the model never saw the structured tool use across
    compaction boundaries.
    """

    from monitor_oop.core.models import ToolCall

    builder = LLMRequestBuilder()
    history = [
        Message(role="user", content="weather?"),
        Message(
            role="assistant",
            content="calling tool",
            tool_calls=[ToolCall(id="call-1", name="weather_lookup", arguments="{}")],
        ),
        Message(
            role="tool",
            content="sunny",
            tool_call_id="call-1",
            name="weather_lookup",
        ),
        Message(role="assistant", content="it is sunny"),
    ]

    result = builder.build_input(history)

    assert result == [
        {"role": "user", "content": "weather?"},
        {
            "role": "assistant",
            "content": "calling tool",
            "tool_calls": [
                {"id": "call-1", "name": "weather_lookup", "arguments": "{}"}
            ],
        },
        {
            "role": "tool",
            "content": "sunny",
            "name": "weather_lookup",
            "tool_call_id": "call-1",
        },
        {"role": "assistant", "content": "it is sunny"},
    ]


def test_build_input_accepts_dict_shaped_tool_calls_unchanged() -> None:
    """Verify dict-form tool_calls (used by some tests) pass through as plain dicts."""

    builder = LLMRequestBuilder()
    history = [
        Message(
            role="assistant",
            content="calling tool",
            tool_calls=[{"id": "call-1", "name": "weather_lookup"}],
        ),
    ]

    result = builder.build_input(history)

    assert result == [
        {
            "role": "assistant",
            "content": "calling tool",
            "tool_calls": [{"id": "call-1", "name": "weather_lookup"}],
        },
    ]


def test_strip_provider_prefix_removes_provider_prefix() -> None:
    """Verify provider-prefixed model names are normalized."""

    builder = LLMRequestBuilder()

    assert builder.strip_provider_prefix("openai/gpt-4o") == "gpt-4o"


def test_strip_provider_prefix_leaves_unprefixed_model_unchanged() -> None:
    """Verify unprefixed model names remain unchanged."""

    builder = LLMRequestBuilder()

    assert builder.strip_provider_prefix("gpt-4o") == "gpt-4o"
