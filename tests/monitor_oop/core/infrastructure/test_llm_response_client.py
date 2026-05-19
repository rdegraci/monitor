"""Tests for LLMResponseClient."""
from __future__ import annotations

import pytest

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.infrastructure.llm_response_client import LLMResponseClient
from monitor_oop.core.infrastructure.rate_limit_service import RateLimitDeniedError


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


class FakeRequestCapacityService:
    """Minimal request capacity service stub for response client tests."""

    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.called = False

    def request_fits(
        self,
        *,
        model: str,
        input_messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        previous_response_id: str | None = None,
    ) -> bool:
        """Record the call and return the configured capacity decision."""

        self.called = True
        return self.allowed


class FakeRateLimitService:
    """Minimal rate limit service stub for response client tests."""

    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.called_estimate = False
        self.called_check_request = False
        self.called_record_request = False
        self.called_record_request_for_model = False
        self.recorded_request_tokens: int | None = None
        self.recorded_request_model: str | None = None

    def estimate_token_usage(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        previous_response_id: str | None = None,
    ) -> int:
        """Record the call and return a stable token estimate."""

        self.called_estimate = True
        return 42

    def check_request(
        self,
        *,
        model: str,
        estimated_tokens: int,
    ) -> None:
        """Record the call; raise RateLimitDeniedError when configured to deny."""

        self.called_check_request = True
        if not self.allowed:
            raise RateLimitDeniedError(
                reason="tpm",
                model=model,
                current=0,
                limit=0,
            )

    def record_request_for_model(self, model: str, tokens: int) -> None:
        """Record the model-aware request usage call."""

        self.called_record_request_for_model = True
        self.recorded_request_model = model
        self.recorded_request_tokens = tokens

    def record_request(self, tokens: int) -> None:
        """Record the request usage call."""

        self.called_record_request = True
        self.recorded_request_tokens = tokens

    def record_response_total_tokens(
        self, response_id: str, total_tokens: int
    ) -> None:
        """Record the chain-aware response-id → total_tokens cache write."""

        self.cached_response_id = response_id
        self.cached_response_total_tokens = total_tokens


def build_config_service() -> ConfigService:
    """Return a config service with stable test values."""

    config_service = ConfigService()
    config_service.get_openai_api_key = lambda: "test-key"  # type: ignore[method-assign]
    config_service.get_api_model_name = lambda: "openai/gpt-5.4-mini"  # type: ignore[method-assign]
    return config_service


def test_create_response_requires_api_key() -> None:
    """Verify the client fails clearly when the API key is missing."""

    config_service = ConfigService()
    config_service.get_openai_api_key = lambda: None  # type: ignore[method-assign]
    client = LLMResponseClient(config_service, adapter=FakeAdapter())

    with pytest.raises(ValueError, match="API key"):
        client.create_response([{"role": "user", "content": "hello"}])


def test_create_response_uses_api_model_name_and_passes_tools() -> None:
    """Verify API model name selection and tool schema wiring for the adapter boundary."""

    fake_adapter = FakeAdapter()

    config_service = build_config_service()

    tool_service = FakeToolService()
    client = LLMResponseClient(config_service, adapter=fake_adapter, tool_service=tool_service)

    response = client.create_response(
        [{"role": "user", "content": "hello"}],
        previous_response_id="response_1",
    )

    assert response == {"ok": True}
    assert tool_service.called is True
    assert len(fake_adapter.calls) == 1
    call = fake_adapter.calls[0]
    assert call["model"] == "openai/gpt-5.4-mini"
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


def test_create_response_uses_unprefixed_api_model_name_unchanged() -> None:
    """Verify unprefixed API model names are passed through unchanged."""

    fake_adapter = FakeAdapter()

    config_service = build_config_service()

    client = LLMResponseClient(config_service, adapter=fake_adapter)

    client.create_response([{"role": "user", "content": "hello"}])

    assert len(fake_adapter.calls) == 1
    assert fake_adapter.calls[0]["model"] == "openai/gpt-5.4-mini"


def test_create_response_invokes_adapter_after_preflights_pass() -> None:
    """Verify capacity and rate-limit preflights both pass before the adapter is called."""

    fake_adapter = FakeAdapter()
    request_capacity_service = FakeRequestCapacityService(allowed=True)
    rate_limit_service = FakeRateLimitService(allowed=True)

    config_service = build_config_service()
    client = LLMResponseClient(
        config_service,
        adapter=fake_adapter,
        request_capacity_service=request_capacity_service,
        rate_limit_service=rate_limit_service,
    )

    response = client.create_response([{"role": "user", "content": "hello"}])

    assert response == {"ok": True}
    assert request_capacity_service.called is True
    assert rate_limit_service.called_estimate is True
    assert rate_limit_service.called_check_request is True
    assert rate_limit_service.called_record_request_for_model is True
    assert rate_limit_service.recorded_request_model == "openai/gpt-5.4-mini"
    assert rate_limit_service.recorded_request_tokens == 42
    assert rate_limit_service.called_record_request is False
    assert len(fake_adapter.calls) == 1


def test_create_response_records_request_usage_after_successful_adapter_call() -> None:
    """Verify request usage is recorded after a successful adapter call."""

    fake_adapter = FakeAdapter()
    rate_limit_service = FakeRateLimitService(allowed=True)

    config_service = build_config_service()
    client = LLMResponseClient(
        config_service,
        adapter=fake_adapter,
        rate_limit_service=rate_limit_service,
    )

    response = client.create_response([{"role": "user", "content": "hello"}])

    assert response == {"ok": True}
    assert rate_limit_service.called_estimate is True
    assert rate_limit_service.called_check_request is True
    assert rate_limit_service.called_record_request_for_model is True
    assert rate_limit_service.recorded_request_model == "openai/gpt-5.4-mini"
    assert rate_limit_service.recorded_request_tokens == 42
    assert rate_limit_service.called_record_request is False
    assert len(fake_adapter.calls) == 1


class _UsageReportingAdapter(FakeAdapter):
    """Adapter that returns a response with provider-reported usage."""

    def __init__(self, total_tokens: int) -> None:
        super().__init__()
        self._total_tokens = total_tokens

    def complete(self, *args, **kwargs):  # type: ignore[override]
        super().complete(*args, **kwargs)
        return {"ok": True, "usage": {"total_tokens": self._total_tokens}}


def test_create_response_records_actual_total_tokens_from_response_usage() -> None:
    """Verify the rate limit service records provider-reported total_tokens, not the estimate."""

    fake_adapter = _UsageReportingAdapter(total_tokens=137)
    rate_limit_service = FakeRateLimitService(allowed=True)

    config_service = build_config_service()
    client = LLMResponseClient(
        config_service,
        adapter=fake_adapter,
        rate_limit_service=rate_limit_service,
    )

    client.create_response([{"role": "user", "content": "hello"}])

    # FakeRateLimitService.estimate_token_usage returns 42 (the preflight
    # estimate); the response reports 137. The recorded value must match the
    # actual provider-reported usage, not the estimate.
    assert rate_limit_service.recorded_request_tokens == 137


class _InputOutputUsageAdapter(FakeAdapter):
    """Adapter returning the Responses-API input/output token shape."""

    def complete(self, *args, **kwargs):  # type: ignore[override]
        super().complete(*args, **kwargs)
        usage = type("Usage", (), {"input_tokens": 80, "output_tokens": 25})()
        return type("Response", (), {"usage": usage})()


def test_create_response_records_actual_tokens_from_input_plus_output_shape() -> None:
    """Verify the recorded value falls back to input_tokens + output_tokens when total_tokens absent."""

    fake_adapter = _InputOutputUsageAdapter()
    rate_limit_service = FakeRateLimitService(allowed=True)

    config_service = build_config_service()
    client = LLMResponseClient(
        config_service,
        adapter=fake_adapter,
        rate_limit_service=rate_limit_service,
    )

    client.create_response([{"role": "user", "content": "hello"}])

    assert rate_limit_service.recorded_request_tokens == 105


def test_create_response_falls_back_to_estimate_when_response_has_no_usage() -> None:
    """Verify the recorded value uses the preflight estimate when the response has no usage payload."""

    fake_adapter = FakeAdapter()  # returns {"ok": True} — no usage key
    rate_limit_service = FakeRateLimitService(allowed=True)

    config_service = build_config_service()
    client = LLMResponseClient(
        config_service,
        adapter=fake_adapter,
        rate_limit_service=rate_limit_service,
    )

    client.create_response([{"role": "user", "content": "hello"}])

    # FakeRateLimitService.estimate_token_usage returns 42; the response has
    # no usage so the recorded value should match the preflight estimate.
    assert rate_limit_service.recorded_request_tokens == 42


class _CachableUsageAdapter(FakeAdapter):
    """Adapter returning a response carrying both ``id`` and ``usage.total_tokens``."""

    def complete(self, *args, **kwargs):  # type: ignore[override]
        super().complete(*args, **kwargs)
        return {"id": "resp_xyz", "usage": {"total_tokens": 175}}


def test_create_response_caches_response_id_total_tokens_for_future_chained_estimates() -> None:
    """Verify the response's id and total_tokens are cached on the rate limit service."""

    fake_adapter = _CachableUsageAdapter()
    rate_limit_service = FakeRateLimitService(allowed=True)

    config_service = build_config_service()
    client = LLMResponseClient(
        config_service,
        adapter=fake_adapter,
        rate_limit_service=rate_limit_service,
    )

    client.create_response([{"role": "user", "content": "hello"}])

    assert rate_limit_service.cached_response_id == "resp_xyz"
    assert rate_limit_service.cached_response_total_tokens == 175


def test_create_response_stops_before_rate_limit_when_capacity_rejects_request() -> None:
    """Verify capacity rejection prevents adapter calls and rate-limit evaluation."""

    fake_adapter = FakeAdapter()
    request_capacity_service = FakeRequestCapacityService(allowed=False)
    rate_limit_service = FakeRateLimitService(allowed=True)

    config_service = build_config_service()
    client = LLMResponseClient(
        config_service,
        adapter=fake_adapter,
        request_capacity_service=request_capacity_service,
        rate_limit_service=rate_limit_service,
    )

    with pytest.raises(ValueError, match="request capacity"):
        client.create_response([{"role": "user", "content": "hello"}])

    assert request_capacity_service.called is True
    assert rate_limit_service.called_estimate is False
    assert rate_limit_service.called_check_request is False
    assert fake_adapter.calls == []


def test_create_response_raises_when_request_capacity_service_rejects_request() -> None:
    """Verify request capacity rejections stop response creation with a clear error."""

    fake_adapter = FakeAdapter()
    request_capacity_service = FakeRequestCapacityService(allowed=False)

    config_service = build_config_service()
    client = LLMResponseClient(
        config_service,
        adapter=fake_adapter,
        request_capacity_service=request_capacity_service,
    )

    with pytest.raises(ValueError, match="request capacity"):
        client.create_response([{"role": "user", "content": "hello"}])

    assert request_capacity_service.called is True
    assert fake_adapter.calls == []


def test_create_response_raises_when_rate_limit_service_rejects_request() -> None:
    """Verify rate limit rejections stop response creation with a typed exception."""

    fake_adapter = FakeAdapter()
    rate_limit_service = FakeRateLimitService(allowed=False)

    config_service = build_config_service()
    client = LLMResponseClient(
        config_service,
        adapter=fake_adapter,
        rate_limit_service=rate_limit_service,
    )

    with pytest.raises(RateLimitDeniedError):
        client.create_response([{"role": "user", "content": "hello"}])

    assert rate_limit_service.called_estimate is True
    assert rate_limit_service.called_check_request is True
    assert fake_adapter.calls == []
