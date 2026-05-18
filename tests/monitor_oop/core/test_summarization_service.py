"""Tests for the SummarizationService token-limit clamp and fallback behavior."""
from __future__ import annotations

from monitor_oop.core.application.llm_request_builder import LLMRequestBuilder
from monitor_oop.core.llm_adapter import ResponsesOpenAiAdapter
from monitor_oop.core.models import Message
from monitor_oop.core.summarization_service import SummarizationService


class _StubConfigService:
    """Minimal config service stub exposing the surfaces summarize() reads."""

    def __init__(self, token_limit: int, output_window: int | None) -> None:
        self._token_limit = token_limit
        self._output_window = output_window

    def get_summarization_token_limit(self) -> int:
        return self._token_limit

    def get_output_window(self) -> int | None:
        return self._output_window

    def get_summarization_prompt_template(self) -> str:
        return "summarize {message_count} messages"


class _RecordingResponseClient:
    """Response client stub that captures the max_output_tokens it received."""

    def __init__(self) -> None:
        self.received_max_output_tokens: int | None = None

    def create_response(
        self,
        request_input,
        previous_response_id=None,
        max_output_tokens=None,
    ):
        self.received_max_output_tokens = max_output_tokens
        return type("Response", (), {"output_text": "summary text"})()


def _build_service(token_limit: int, output_window: int | None) -> tuple[
    SummarizationService, _RecordingResponseClient
]:
    config = _StubConfigService(token_limit=token_limit, output_window=output_window)
    response_client = _RecordingResponseClient()
    service = SummarizationService(
        config_service=config,
        request_builder=LLMRequestBuilder(),
        response_client=response_client,
        response_adapter=ResponsesOpenAiAdapter(),
    )
    return service, response_client


def test_token_limit_clamped_when_above_output_window() -> None:
    """Verify token_limit greater than output_window is clamped before reaching the adapter."""

    service, response_client = _build_service(token_limit=8_000, output_window=4_096)

    service.summarize([Message(role="user", content="hello")])

    assert response_client.received_max_output_tokens == 4_096


def test_token_limit_unchanged_when_below_output_window() -> None:
    """Verify token_limit smaller than output_window is preserved as-is."""

    service, response_client = _build_service(token_limit=1_024, output_window=4_096)

    service.summarize([Message(role="user", content="hello")])

    assert response_client.received_max_output_tokens == 1_024


def test_token_limit_unchanged_when_output_window_missing() -> None:
    """Verify token_limit is not clamped when no output_window is available."""

    service, response_client = _build_service(token_limit=8_000, output_window=None)

    service.summarize([Message(role="user", content="hello")])

    assert response_client.received_max_output_tokens == 8_000


class _FailingResponseClient:
    """Response client stub that always raises, forcing the fallback path."""

    def create_response(
        self,
        request_input,
        previous_response_id=None,
        max_output_tokens=None,
    ):
        raise RuntimeError("simulated LLM failure")


def _build_service_with_failing_client(
    token_limit: int = 4_000,
    output_window: int | None = None,
) -> SummarizationService:
    config = _StubConfigService(token_limit=token_limit, output_window=output_window)
    return SummarizationService(
        config_service=config,
        request_builder=LLMRequestBuilder(),
        response_client=_FailingResponseClient(),
        response_adapter=ResponsesOpenAiAdapter(),
    )


def test_fallback_returns_placeholder_only_when_no_prior_summary_exists() -> None:
    """Verify a first-time fallback emits only the placeholder line."""

    service = _build_service_with_failing_client()

    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
    ]
    result = service.summarize(messages)

    assert result == "[Compacted summary placeholder for 2 prior messages]"


def test_fallback_carries_forward_prior_summary_under_cap() -> None:
    """Verify a small prior system summary is preserved verbatim before the new placeholder."""

    service = _build_service_with_failing_client(token_limit=4_000)

    prior_summary = "real LLM-derived summary of earlier turns"
    messages = [
        Message(role="system", content=prior_summary),
        Message(role="user", content="follow-up"),
    ]
    result = service.summarize(messages)

    assert result == (
        f"{prior_summary}\n\n[Compacted summary placeholder for 2 prior messages]"
    )


def test_fallback_truncates_prior_summary_when_over_cap() -> None:
    """Verify an oversized prior summary is truncated from the end to fit the cap."""

    # token_limit=10 → cap = 10 * 4 chars per token = 40 chars.
    service = _build_service_with_failing_client(token_limit=10)

    prior_summary = "A" * 60
    messages = [
        Message(role="system", content=prior_summary),
        Message(role="user", content="new turn"),
    ]
    result = service.summarize(messages)

    expected_prior_head = "A" * 40
    assert result == (
        f"{expected_prior_head}\n[... summary truncated to fit cap ...]"
        f"\n\n[Compacted summary placeholder for 2 prior messages]"
    )


def test_fallback_only_treats_leading_system_message_as_prior_summary() -> None:
    """Verify a system message after the head is not mistaken for a prior summary."""

    service = _build_service_with_failing_client()

    messages = [
        Message(role="user", content="hi"),
        Message(role="system", content="tool-injected notice, not a summary"),
        Message(role="assistant", content="hello"),
    ]
    result = service.summarize(messages)

    assert result == "[Compacted summary placeholder for 3 prior messages]"
