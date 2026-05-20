"""Tests for ResponsesOpenAiAdapter in the Monitor OOP core layer."""
from __future__ import annotations

from monitor_oop.core.llm_adapter import ResponsesOpenAiAdapter


class OutputTextResponse:
    """Response double exposing output_text."""

    def __init__(self, text: str) -> None:
        self.output_text = text


def test_extract_text_prefers_output_text() -> None:
    """Verify output_text is returned when available."""

    adapter = ResponsesOpenAiAdapter()

    assert adapter.extract_text(OutputTextResponse("hello world")) == "hello world"


def test_complete_omits_empty_optional_fields_from_openai_request(monkeypatch) -> None:
    """Verify the OpenAI Responses request omits unset optional fields.

    The adapter's external surface is the call to ``client.responses.create(...)``.
    Patching the ``OpenAI`` constructor lets the test inspect exactly which
    kwargs reach the provider, without reaching into the adapter's internals.
    """

    captured_kwargs: dict = {}

    class _CapturingResponses:
        def create(self, **kwargs):
            captured_kwargs.update(kwargs)
            return object()

    class _CapturingClient:
        def __init__(self, api_key: str) -> None:
            self.responses = _CapturingResponses()

    monkeypatch.setattr("monitor_oop.core.llm_adapter.OpenAI", _CapturingClient)

    adapter = ResponsesOpenAiAdapter()
    adapter.complete(
        model="gpt-4o",
        input=[{"role": "user", "content": "hello"}],
        api_key="test-key",
        tools=None,
        tool_choice=None,
        previous_response_id=None,
    )

    assert captured_kwargs == {
        "model": "gpt-4o",
        "input": [{"role": "user", "content": "hello"}],
    }
