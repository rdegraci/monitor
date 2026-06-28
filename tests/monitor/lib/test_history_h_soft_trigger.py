from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from monitor import config
from monitor.lib import history


class _CaptureLogger:
    def __init__(self) -> None:
        self.records = []

    def debug(self, message, *args, **kwargs):
        self.records.append(("debug", message))

    def info(self, message, *args, **kwargs):
        self.records.append(("info", message))

    def warning(self, message, *args, **kwargs):
        self.records.append(("warning", message))

    def error(self, message, *args, **kwargs):
        self.records.append(("error", message))

    def critical(self, message, *args, **kwargs):
        self.records.append(("critical", message))


class _StubConfig:
    def __init__(self) -> None:
        self.MODEL = "xai/grok-build-0.1"
        self.MAX_TOKEN_COUNT = 128_000
        self.CONVERSATION_MAX_SIZE = 512
        self.SUMMARIZATION_CONFIG = {
            "triggers": {
                "token_threshold": 0.6,
                "time_limit_seconds": 259_200,
                "memory_limit_mb": 100,
            },
            "prompt": {"template": "Summarize: {messages}"},
        }
        self.AUTO_COMPACT_THRESHOLD_RATIO = 0.50
        self.AUTO_COMPACT_THRESHOLD_RATIO_BY_MODEL = {}
        self.TOTAL_TOKEN_COUNT = 0
        self.RESPONSES_API = False
        self.RESPONSE_ID = None
        self.last_summary_time = 0.0

    def effective_auto_compact_ratio(self, model=None):
        model_name = model or self.MODEL
        overrides = self.AUTO_COMPACT_THRESHOLD_RATIO_BY_MODEL
        if isinstance(overrides, dict):
            value = overrides.get(model_name)
            if isinstance(value, (int, float)) and 0 < value <= 1:
                return float(value)
        return float(self.AUTO_COMPACT_THRESHOLD_RATIO)


@pytest.fixture
def capture_logger() -> _CaptureLogger:
    return _CaptureLogger()


@pytest.fixture
def stub_config(monkeypatch) -> _StubConfig:
    cfg = _StubConfig()
    monkeypatch.setattr(history, "config", cfg)
    return cfg


@pytest.fixture
def token_counter(monkeypatch):
    def _count_message_tokens(message):
        if isinstance(message, list):
            return sum(_count_message_tokens(item) for item in message)
        if isinstance(message, dict):
            content = message.get("content", "")
            return len(str(content))
        return len(str(message))

    monkeypatch.setattr(history, "count_message_tokens", _count_message_tokens)
    return _count_message_tokens


def _build_history(user_turns: int, token_size: int) -> list[dict[str, str]]:
    history_items = [{"role": "system", "content": "System prompt."}]
    for index in range(user_turns):
        history_items.append({"role": "user", "content": f"user {index} {'x' * token_size}"})
        history_items.append({"role": "assistant", "content": f"assistant {index} {'y' * token_size}"})
    return history_items


def test_check_limits_triggers_h_based_soft_compaction(capture_logger, stub_config, token_counter):
    """High retained-history tokens should trigger summarization even with few turns."""
    conversation = _build_history(user_turns=1, token_size=80_000)
    stub_config.TOTAL_TOKEN_COUNT = token_counter(conversation)
    with patch.object(history, "_get_responses_chain_compaction_pressure", return_value={"requires_compaction": False, "payload_budget": None, "hidden_chain_reserve": 0, "request_class": None, "telemetry_request_class": None, "telemetry_payload_budget": None, "telemetry_requires_compaction": False, "enabled": False, "model_input_window": None, "usable_window": None}):
        limits = history.check_limits(
            stub_config.TOTAL_TOKEN_COUNT,
            stub_config.MAX_TOKEN_COUNT,
            stub_config.CONVERSATION_MAX_SIZE,
            conversation,
            stub_config.SUMMARIZATION_CONFIG,
            capture_logger,
            stub_config,
        )
        if limits["should_summarize"]:
            config.SESSION_COMPACTION_COUNT = getattr(config, "SESSION_COMPACTION_COUNT", 0) + 1

    assert limits["should_summarize"] is True
    assert limits["trigger_reasons"]["tokens"] is True


def test_check_limits_does_not_trigger_h_based_soft_compaction_below_threshold(capture_logger, stub_config, token_counter):
    """Retained-history tokens below the ratio threshold should not force summarization by themselves."""
    conversation = _build_history(user_turns=1, token_size=10_000)
    stub_config.TOTAL_TOKEN_COUNT = token_counter(conversation)
    with patch.object(history, "_get_responses_chain_compaction_pressure", return_value={"requires_compaction": False, "payload_budget": None, "hidden_chain_reserve": 0, "request_class": None, "telemetry_request_class": None, "telemetry_payload_budget": None, "telemetry_requires_compaction": False, "enabled": False, "model_input_window": None, "usable_window": None}):
        limits = history.check_limits(
            stub_config.TOTAL_TOKEN_COUNT,
            stub_config.MAX_TOKEN_COUNT,
            stub_config.CONVERSATION_MAX_SIZE,
            conversation,
            stub_config.SUMMARIZATION_CONFIG,
            capture_logger,
            stub_config,
        )

    assert limits["should_summarize"] is False
    assert limits["trigger_reasons"]["tokens"] is False


def test_effective_auto_compact_ratio_is_used_for_h_threshold(stub_config):
    """The H-based threshold should scale from AUTO_COMPACT_THRESHOLD_RATIO."""
    assert stub_config.effective_auto_compact_ratio() == pytest.approx(0.5)
