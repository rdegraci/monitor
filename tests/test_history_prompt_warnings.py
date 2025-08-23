import logging
import pytest

import monitor.lib.history as history


class DummyConfig:
    def __init__(self, max_token_count=100, token_threshold=0.8):
        self.TOTAL_TOKEN_COUNT = 0
        self.MAX_TOKEN_COUNT = max_token_count
        self.CONVERSATION_MAX_SIZE = 100
        self.SUMMARIZATION_CONFIG = {
            'triggers': {
                'token_threshold': token_threshold,
                'time_limit_seconds': 3600,
                'memory_limit_mb': 1024,
            },
            'prompt': {'template': 'Please summarize: {messages}'},
        }
        self.MODEL = "gpt-unit-test"
        self.last_summary_time = 0
        self.EXTERNAL_SERVICES = False


def _count_10(msg):
    if isinstance(msg, (list, tuple)):
        return sum(_count_10(m) for m in msg)
    return 10


def _noop(*args, **kwargs):
    return None


@pytest.fixture
def caplog_info(caplog):
    caplog.set_level(logging.INFO)
    return caplog


def test_prompt_warning_prefix_when_over_threshold_without_summarization(monkeypatch, caplog_info):
    # Arrange
    cfg = DummyConfig(max_token_count=100, token_threshold=0.8)  # threshold -> 80 tokens
    # Build history close to threshold; add many messages so that after appending new user_input, we cross >= 80
    conversation = [{"role": "system", "content": "sys"}] + [
        {"role": "user", "content": f"m{i}"} for i in range(7)
    ]
    # tokens_in_history pre-append: (1 + 7) * 10 = 80
    # After appending user_input (+10) -> 90, which is >= threshold

    # Patch token counting to controlled 10 tokens per message and disable token usage updates
    monkeypatch.setattr(history, "count_message_tokens", _count_10)
    monkeypatch.setattr(history, "update_token_usage", _noop)

    # Stub check_limits to claim no summarization should happen
    def fake_check_limits(tokens_in_history, *_args, **_kwargs):
        return {
            'should_summarize': False,
            'trigger_reasons': {'tokens': False, 'history': False, 'time': False, 'memory': False},
            'metrics': {'token_count': tokens_in_history, 'token_limit': cfg.MAX_TOKEN_COUNT * cfg.SUMMARIZATION_CONFIG['triggers']['token_threshold']}
        }

    logger = logging.getLogger("test_prompt_warning_prefix")

    # Act
    history.append_conversation_history(
        user_input="hello",  # +10 tokens
        conversation_history=conversation,
        conversation_logs_func=_noop,
        handle_token_limit_func=lambda max_t, total_t: max_t,
        check_limits_func=fake_check_limits,
        generate_summary_func=_noop,
        reset_with_summary_func=_noop,
        system_prompt="sys",
        config=cfg,
        post_social_summaries_func=_noop,
        logger=logger,
    )

    # Assert: Expect a prompt warning with the exact prefix
    records = [r for r in caplog_info.records if r.levelno >= logging.WARNING]
    messages = "\n".join(r.getMessage() for r in records)
    assert "[SUMMARIZATION][PROMPT]" in messages, f"Expected prompt warning prefix not found. Logs:\n{messages}"
    assert "80%" in messages, f"Expected threshold percent (80%) in warning. Logs:\n{messages}"


def test_guard_error_on_invalid_max_token_count(monkeypatch, caplog_info):
    # Arrange: invalid MAX_TOKEN_COUNT that fails int() coercion in guard
    cfg = DummyConfig(max_token_count=100, token_threshold=0.9)
    cfg.MAX_TOKEN_COUNT = "not_an_int"
    conversation = [{"role": "system", "content": "sys"}]

    # Ensure token counting works and update usage is a no-op
    monkeypatch.setattr(history, "count_message_tokens", _count_10)
    monkeypatch.setattr(history, "update_token_usage", _noop)

    # Stub check_limits to avoid summarization (so we enter else branch with guard)
    def fake_check_limits(tokens_in_history, *_args, **_kwargs):
        return {
            'should_summarize': False,
            'trigger_reasons': {'tokens': False, 'history': False, 'time': False, 'memory': False},
            'metrics': {'token_count': tokens_in_history}
        }

    logger = logging.getLogger("test_guard_invalid_max_tokens")

    # Act + Assert
    with pytest.raises(RuntimeError):
        history.append_conversation_history(
            user_input="trigger",
            conversation_history=conversation,
            conversation_logs_func=_noop,
            handle_token_limit_func=lambda max_t, total_t: max_t,
            check_limits_func=fake_check_limits,
            generate_summary_func=_noop,
            reset_with_summary_func=_noop,
            system_prompt="sys",
            config=cfg,
            post_social_summaries_func=_noop,
            logger=logger,
        )

    messages = "\n".join(r.getMessage() for r in caplog_info.records)
    assert "Invalid or missing MAX_TOKEN_COUNT" in messages, f"Expected guard error log not found. Logs:\n{messages}"


def test_cumulative_warning_prefixes_in_log_negative_token_count(caplog_info):
    # Arrange logger
    logger = logging.getLogger("test_cumulative_prefix")

    # Case 1: > 95% of MAX_TOKEN_COUNT should warn with [TOKEN COUNT][CUMULATIVE]
    cfg = DummyConfig(max_token_count=100)
    cfg.TOTAL_TOKEN_COUNT = 96
    history.log_negative_token_count(logger, cfg)

    # Case 2: > 2x MAX_TOKEN_COUNT should warn with [TOKEN COUNT][CUMULATIVE]
    cfg2 = DummyConfig(max_token_count=100)
    cfg2.TOTAL_TOKEN_COUNT = 205
    history.log_negative_token_count(logger, cfg2)

    # Assert
    warnings = [r.getMessage() for r in caplog_info.records if r.levelno >= logging.WARNING]
    joined = "\n".join(warnings)
    assert any("[TOKEN COUNT][CUMULATIVE]" in m and "(96)" in m for m in warnings), f"Expected near-threshold cumulative warning with (96). Logs:\n{joined}"
    assert any("[TOKEN COUNT][CUMULATIVE]" in m and "(205)" in m for m in warnings), f"Expected >2x cumulative warning with (205). Logs:\n{joined}"
