"""Tests for LLMRequestBuilder."""
from monitor_oop.core.application.llm_request_builder import LLMRequestBuilder
from monitor_oop.core.models import Message


def test_build_input_converts_history_and_appends_user_input() -> None:
    """Verify request input preserves history order and appends the latest user input."""

    builder = LLMRequestBuilder()
    history = [
        Message(role="system", content="system note"),
        "prior user text",
        Message(role="assistant", content="assistant reply"),
    ]

    result = builder.build_input("current user text", history)

    assert result == [
        {"role": "system", "content": "system note"},
        {"role": "user", "content": "prior user text"},
        {"role": "assistant", "content": "assistant reply"},
        {"role": "user", "content": "current user text"},
    ]


def test_strip_provider_prefix_removes_provider_prefix() -> None:
    """Verify provider-prefixed model names are normalized."""

    builder = LLMRequestBuilder()

    assert builder.strip_provider_prefix("openai/gpt-4o") == "gpt-4o"


def test_strip_provider_prefix_leaves_unprefixed_model_unchanged() -> None:
    """Verify unprefixed model names remain unchanged."""

    builder = LLMRequestBuilder()

    assert builder.strip_provider_prefix("gpt-4o") == "gpt-4o"
