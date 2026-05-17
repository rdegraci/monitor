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


def test_build_request_kwargs_omits_empty_optional_fields() -> None:
    """Verify request kwargs include only populated optional fields."""

    adapter = ResponsesOpenAiAdapter()

    kwargs = adapter._build_request_kwargs(
        model="gpt-4o",
        input=[{"role": "user", "content": "hello"}],
        tools=None,
        tool_choice=None,
        previous_response_id=None,
    )

    assert kwargs == {
        "model": "gpt-4o",
        "input": [{"role": "user", "content": "hello"}],
    }
