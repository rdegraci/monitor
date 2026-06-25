import pytest
import logging
import monitor.lib.history as history
from unittest import mock
from unittest.mock import patch  # Added for mocking core.llm.get_llm_completion
from types import SimpleNamespace
import time

# Import format_prompt_display if required
from monitor.lib.display_output import format_prompt_display


class DummyConfig:
    """Configuration stub for testing."""

    def __init__(self):
        self.TOTAL_TOKEN_COUNT = 0
        self.MAX_TOKEN_COUNT = 1200
        self.CONVERSATION_MAX_SIZE = 12
        self.SUMMARIZATION_CONFIG = {
            "triggers": {
                "token_threshold": 0.7,
                "time_limit_seconds": 3600,
                "memory_limit_mb": 50,
            },
            "prompt": {"template": "Please summarize: {messages}"},
        }
        self.MODEL = "gpt-3-test"
        self.last_summary_time = 0
        self.EXTERNAL_SERVICES = False

    def __getattr__(self, name):
        raise AttributeError(f"DummyConfig has no attribute {name}")


def dummy_update_token_usage(tokens_or_response):
    pass


def fake_litellm_completion_func(**kwargs):
    class Resp:
        class Choice:
            def __init__(self):
                self.message = {"role": "summary", "content": "Short summary."}

        def __init__(self):
            self.choices = [self.Choice()]
            self.usage = SimpleNamespace(total_tokens=7)

    return Resp()


@pytest.fixture
def sample_conversation():
    return [
        {"role": "system", "content": "System prompt."},
    ] + [{"role": "user", "content": f"Msg {i}"} for i in range(10)]


@pytest.fixture
def logger():
    logger = logging.getLogger("test_history_suite")
    logger.setLevel(logging.INFO)
    return logger


@pytest.fixture
def config():
    return DummyConfig()


def count_message_tokens_always_10(msg):
    if isinstance(msg, (list, tuple)):
        return sum(count_message_tokens_always_10(m) for m in msg)
    return 10


def recount_conversation_tokens(conversation, token_counter):
    return sum(token_counter(msg) for msg in conversation)


def append_to_history_with_count_test(
    message, conversation, config, logger,
):
    tokens = count_message_tokens_always_10(message)
    conversation.append(message)
    config.TOTAL_TOKEN_COUNT += tokens
    logger.info(f"Appended message; token count now {config.TOTAL_TOKEN_COUNT}")
    return tokens


@pytest.fixture
def conversation_and_config(sample_conversation, config):
    conversation = [msg.copy() for msg in sample_conversation]
    config.TOTAL_TOKEN_COUNT = recount_conversation_tokens(
        conversation, count_message_tokens_always_10
    )
    return conversation, config


@pytest.mark.parametrize(
    "trigger,modify_func,expected_trigger",
    [
        (
            "token_threshold",
            lambda convo, cfg: _fill_tokens_to_threshold(
                cfg, convo, cfg.SUMMARIZATION_CONFIG, cfg.MAX_TOKEN_COUNT
            ),
            True,
        ),
        # NOTE: a "conversation_size" positive case used to live here. It tested
        # that hitting CONVERSATION_MAX_SIZE (with token pressure) triggered
        # summarization. The trigger has been removed (token pressure alone now
        # drives compaction; message count is observation-only), so the positive
        # case no longer applies. The two negative cases below still verify that
        # conversation_size does NOT cause summarization on its own.
        (
            "time_limit_seconds",
            lambda convo, cfg: _simulate_time_trigger(
                cfg,
                convo,
                cfg.SUMMARIZATION_CONFIG["triggers"]["time_limit_seconds"],
            ),
            True,
        ),
        (
            "memory_limit_mb",
            lambda convo, cfg: _simulate_memory_trigger(
                cfg,
                convo,
                cfg.SUMMARIZATION_CONFIG["triggers"]["memory_limit_mb"],
            ),
            True,
        ),
        (
            "token_threshold (negative)",
            lambda convo, cfg: _set_strictly_below_token_threshold(
                cfg,
                convo,
                cfg.SUMMARIZATION_CONFIG,
                cfg.MAX_TOKEN_COUNT,
                logger=cfg.__dict__.get("_pytest_logger"),
            ),
            False,
        ),
        (
            "conversation_size (negative)",
            lambda convo, cfg: _set_strictly_below_conversation_size(
                cfg,
                convo,
                cfg.CONVERSATION_MAX_SIZE,
                logger=cfg.__dict__.get("_pytest_logger"),
            ),
            False,
        ),
        (
            "time_limit_seconds (negative)",
            lambda convo, cfg: _set_strictly_below_time_trigger(
                cfg,
                convo,
                cfg.SUMMARIZATION_CONFIG["triggers"]["time_limit_seconds"],
            ),
            False,
        ),
        (
            "memory_limit_mb (negative)",
            lambda convo, cfg: _set_strictly_below_memory_trigger(
                cfg,
                convo,
                cfg.SUMMARIZATION_CONFIG["triggers"]["memory_limit_mb"],
                logger=cfg.__dict__.get("_pytest_logger"),
            ),
            False,
        ),
        # Regression: secondary triggers alone (without token pressure) should
        # NOT drive summarization. Each of these sets up a non-token trigger and
        # explicitly keeps TOTAL_TOKEN_COUNT below the secondary-pressure
        # threshold (50% of MAX_TOKEN_COUNT). The previous behavior summarized
        # in all of these cases, which produced nuisance compactions on idle
        # pauses, short-message overrun, etc.
        (
            "conversation_size without token pressure",
            lambda convo, cfg: _fill_to_conversation_size_no_token_pressure(
                cfg, convo, cfg.CONVERSATION_MAX_SIZE
            ),
            False,
        ),
        (
            "time_limit_seconds without token pressure",
            lambda convo, cfg: _simulate_time_trigger_no_token_pressure(
                cfg,
                convo,
                cfg.SUMMARIZATION_CONFIG["triggers"]["time_limit_seconds"],
            ),
            False,
        ),
    ],
)
def test_summarization_triggers_and_reset(
    trigger, modify_func, expected_trigger, conversation_and_config, logger, monkeypatch
):
    """Test that each supported summarization trigger correctly initiates summarization,
    resets conversation, and resets token counts, and verify the negatives do not.

    Args:
        trigger (str): Name of the trigger under test.
        modify_func (callable): Callable to adjust conversation/config state to hit the trigger.
        expected_trigger (bool): Whether summarization should be required after invoking `modify_func`.
        conversation_and_config (tuple): (conversation, config) initial state.
        logger (Logger): Logger for test output.
        monkeypatch (pytest.MonkeyPatch): Monkeypatching utility.
    """
    conversation, config = conversation_and_config

    # Attach logger to config for negative cases needing a logger in function args
    config._pytest_logger = logger

    monkeypatch.setattr(history, "count_message_tokens", count_message_tokens_always_10)
    monkeypatch.setattr(history, "update_token_usage", dummy_update_token_usage)
    fake_now = [100000.0]
    monkeypatch.setattr(time, "time", lambda: fake_now[0])

    logger.info(f"== TEST: Trigger {trigger}, expecting summarization: {expected_trigger} ==")
    orig_token_count = config.TOTAL_TOKEN_COUNT

    if modify_func is not None:
        modify_func(conversation, config)

    limits = history.check_limits(
        config.TOTAL_TOKEN_COUNT,
        config.MAX_TOKEN_COUNT,
        config.CONVERSATION_MAX_SIZE,
        conversation,
        config.SUMMARIZATION_CONFIG,
        logger,
        config,
    )
    logger.info(f"Limits result: {limits}")
    should_summarize = limits.get("should_summarize", False)
    if expected_trigger:
        assert (
            should_summarize
        ), f"Expected summarization for trigger '{trigger}', but it was not triggered"
    else:
        assert (
            not should_summarize
        ), f"Did not expect summarization for negative case of '{trigger}'"

    if should_summarize:
        pre_reset_len = len(conversation)
        pre_reset_tokens = config.TOTAL_TOKEN_COUNT
        system_prompt = next(
            (m["content"] for m in conversation if m["role"] == "system"),
            "System prompt.",
        )
        # Use unittest.mock.patch to mock the LLM call at the specific import path.
        with patch("monitor.core.llm.get_llm_completion") as mock_llm:
            mock_llm.return_value = fake_litellm_completion_func()
            summary_resp = mock_llm()

            def append_func(m, hist, count_func, update_func):
                count = count_message_tokens_always_10(m)
                hist.append(m)
                config.TOTAL_TOKEN_COUNT += count
                logger.info(f"Appended message; token count now {config.TOTAL_TOKEN_COUNT}")
                return count

            # set_token_count_func removed: function and argument
            history.reset_conversation_with_summary(
                summary=summary_resp.choices[0].message["content"],
                system_prompt=system_prompt,
                user_input="User resumed after summary.",
                conversation_history=conversation,
                append_func=append_func,
                logger=logger,
                config=config,
            )

        logger.info(
            f"After reset: conversation len={len(conversation)}, tokens={config.TOTAL_TOKEN_COUNT}"
        )
        assert len(conversation) >= 2
        recounted = recount_conversation_tokens(
            conversation, count_message_tokens_always_10
        )
        assert config.TOTAL_TOKEN_COUNT == recounted
        summary_content = summary_resp.choices[0].message["content"]
        found_summary_content = any(
            summary_content in m.get("content", "") for m in conversation
        )
        assert (
            found_summary_content
        ), "Reset conversation must include the summary message content."
    else:
        assert config.TOTAL_TOKEN_COUNT == recount_conversation_tokens(
            conversation, count_message_tokens_always_10
        )


def test_check_limits_triggers_summarization_for_responses_chain_budget_pressure(
    logger, config
):
    """Reserve-aware Responses chain pressure should force compaction even when visible tokens look safe."""
    conversation = [
        {"role": "system", "content": "System prompt."},
        {"role": "user", "content": "Recent user turn."},
        {"role": "assistant", "content": "Recent assistant turn."},
    ]
    config.TOTAL_TOKEN_COUNT = 30
    config.CONVERSATION_HISTORY = conversation
    config.RESPONSES_API = True
    config.RESPONSE_ID = "resp_chain"
    config.MODEL = "openai/gpt-4o-mini"
    config.MODEL_INPUT_WINDOW = 1000
    config.MODEL_CONTEXT_WINDOW = 1200

    telemetry_budget = (
        {},
        {
            "request_class": "chained_user_followup",
            "model_input_window": 1000,
            "usable_window": 850,
            "hidden_chain_reserve": 900,
            "payload_budget": -50,
            "decision": "fallback",
        },
    )
    hard_budget = (
        {},
        {
            "request_class": "chained_user_followup",
            "model_input_window": 1000,
            "usable_window": 850,
            "hidden_chain_reserve": 900,
            "payload_budget": -50,
            "decision": "fallback",
        },
    )

    with patch(
        "monitor.core.llm_responses_adapter.budget_followup_request",
        side_effect=[telemetry_budget, hard_budget],
    ):
        limits = history.check_limits(
            config.TOTAL_TOKEN_COUNT,
            config.MAX_TOKEN_COUNT,
            config.CONVERSATION_MAX_SIZE,
            conversation,
            config.SUMMARIZATION_CONFIG,
            logger,
            config,
        )

    assert limits["should_summarize"] is True
    assert limits["trigger_reasons"]["tokens"] is False
    assert limits["trigger_reasons"]["responses_chain_budget"] is True
    assert limits["metrics"]["responses_chain_payload_budget"] == -50
    assert limits["metrics"]["responses_chain_hidden_chain_reserve"] == 900
    assert limits["metrics"]["responses_chain_request_class"] == "chained_user_followup"


def test_check_limits_uses_real_next_user_shape_for_hard_trigger_and_history_probe_for_telemetry(
    logger, config
):
    """Use the latest user input for the hard trigger while preserving history-shaped telemetry."""
    conversation = [
        {"role": "system", "content": "System prompt."},
        {"role": "user", "content": "Short latest user turn."},
        {"role": "assistant", "content": "Assistant reply."},
    ]
    config.TOTAL_TOKEN_COUNT = 30
    config.CONVERSATION_HISTORY = conversation
    config.RESPONSES_API = True
    config.RESPONSE_ID = "resp_chain"
    config.MODEL = "openai/gpt-4o-mini"
    config.MODEL_INPUT_WINDOW = 1000
    config.MODEL_CONTEXT_WINDOW = 1200

    telemetry_budget = (
        {},
        {
            "request_class": "chained_user_followup",
            "model_input_window": 1000,
            "usable_window": 850,
            "hidden_chain_reserve": 900,
            "payload_budget": -50,
            "decision": "fallback",
        },
    )
    hard_budget = (
        {},
        {
            "request_class": "chained_user_followup",
            "model_input_window": 1000,
            "usable_window": 850,
            "hidden_chain_reserve": 900,
            "payload_budget": 25,
            "decision": "send",
        },
    )

    with patch(
        "monitor.core.llm_responses_adapter.budget_followup_request",
        side_effect=[telemetry_budget, hard_budget],
    ) as mock_budget:
        limits = history.check_limits(
            config.TOTAL_TOKEN_COUNT,
            config.MAX_TOKEN_COUNT,
            config.CONVERSATION_MAX_SIZE,
            conversation,
            config.SUMMARIZATION_CONFIG,
            logger,
            config,
        )

    assert mock_budget.call_count == 2
    telemetry_call = mock_budget.call_args_list[0].args[0]
    hard_call = mock_budget.call_args_list[1].args[0]
    assert telemetry_call["input"] == conversation
    assert hard_call["input"] == "Short latest user turn."
    assert limits["should_summarize"] is False
    assert limits["trigger_reasons"]["responses_chain_budget"] is False
    assert limits["metrics"]["responses_chain_payload_budget"] == 25
    assert limits["metrics"]["responses_chain_hidden_chain_reserve"] == 900
    assert limits["metrics"]["responses_chain_request_class"] == "chained_user_followup"



def test_responses_chain_pressure_uses_turn_round_trips_for_chained_budget_depth(config):
    conversation = [
        {"role": "user", "content": "First turn."},
        {"role": "assistant", "content": "First answer."},
        {"role": "user", "content": "Follow-up turn."},
    ]
    config.CONVERSATION_HISTORY = conversation
    config.RESPONSES_API = True
    config.RESPONSE_ID = "resp_chain"
    config.MODEL = "openai/gpt-4o-mini"
    config.MODEL_INPUT_WINDOW = 1_000
    config.MODEL_CONTEXT_WINDOW = 1_200
    config.TURN_ROUND_TRIPS = [2, 30]

    with patch(
        "monitor.core.llm_responses_adapter.infer_followup_iteration",
        return_value=30,
    ) as mock_infer, patch(
        "monitor.core.llm_responses_adapter.budget_followup_request"
    ) as mock_snapshot:
        mock_snapshot.return_value = (
            {},
            {
                "request_class": "chained_user_followup",
                "model_input_window": 1_000,
                "usable_window": 850,
                "hidden_chain_reserve": 4_400,
                "payload_budget": 50,
                "decision": "send",
            },
        )
        history._get_responses_chain_compaction_pressure(config, logging.getLogger(__name__))

    assert mock_infer.call_count == 1
    assert mock_snapshot.call_count == 2
    assert mock_snapshot.call_args_list[0].kwargs["iteration"] == 30
    assert mock_snapshot.call_args_list[1].kwargs["iteration"] == 30

def _fill_tokens_to_threshold(
    config, conversation, summarization_config, max_token_count
):
    threshold_pct = summarization_config["triggers"]["token_threshold"]
    threshold_tokens = int(max_token_count * threshold_pct)
    while config.TOTAL_TOKEN_COUNT < threshold_tokens + 1:
        msg = {
            "role": "user",
            "content": f"Payload token_filler {config.TOTAL_TOKEN_COUNT}",
        }
        conversation.append(msg)
        config.TOTAL_TOKEN_COUNT += count_message_tokens_always_10(msg)


def _ensure_secondary_pressure(config, conversation):
    """Bring TOTAL_TOKEN_COUNT above 50% of MAX_TOKEN_COUNT.

    Secondary triggers (history-size, time, memory) only contribute to
    summarization when token usage is also above the secondary-pressure
    threshold (currently 0.5 * MAX_TOKEN_COUNT). Tests that simulate a
    secondary trigger in isolation need to pre-load tokens so the trigger
    actually drives summarization.
    """
    target = int(config.MAX_TOKEN_COUNT * 0.5) + 10
    while config.TOTAL_TOKEN_COUNT < target:
        msg = {
            "role": "user",
            "content": f"pressure_filler {config.TOTAL_TOKEN_COUNT}",
        }
        conversation.append(msg)
        config.TOTAL_TOKEN_COUNT += count_message_tokens_always_10(msg)


def _fill_to_conversation_size(config, conversation, conversation_max_size):
    while len(conversation) <= conversation_max_size:
        msg = {"role": "user", "content": f"Payload size_filler {len(conversation)}"}
        conversation.append(msg)
        config.TOTAL_TOKEN_COUNT += count_message_tokens_always_10(msg)
    # Secondary triggers now require token pressure to drive summarization.
    _ensure_secondary_pressure(config, conversation)


def _simulate_time_trigger(config, conversation, time_limit_seconds):
    config.last_summary_time = 0
    current_time = 100000.0
    future_time = current_time + time_limit_seconds + 10
    config._fake_now = future_time
    # Secondary triggers now require token pressure to drive summarization.
    _ensure_secondary_pressure(config, conversation)


def _simulate_memory_trigger(config, conversation, memory_limit_mb):
    bytes_needed = int((memory_limit_mb + 5) * 1024 * 1024)

    class FakeList(list):
        def __sizeof__(self_inner):
            return bytes_needed

    conversation[:] = FakeList(conversation)
    # Secondary triggers now require token pressure to drive summarization.
    _ensure_secondary_pressure(config, conversation)


def _fill_to_conversation_size_no_token_pressure(
    config, conversation, conversation_max_size
):
    """Fill conversation past CONVERSATION_MAX_SIZE while keeping tokens below
    the secondary-pressure threshold. Used by the regression test that locks
    in 'secondary trigger without token pressure → no summarization'."""
    while len(conversation) <= conversation_max_size:
        msg = {"role": "user", "content": f"size_only {len(conversation)}"}
        conversation.append(msg)
        config.TOTAL_TOKEN_COUNT += count_message_tokens_always_10(msg)
    # Ensure token usage stays strictly below the secondary-pressure threshold
    # (0.5 * MAX_TOKEN_COUNT). With MAX_TOKEN_COUNT=1200 and ~13 messages of
    # 10 tokens, we're at ~130 << 600, so no extra clamping is required, but
    # we assert here so future config bumps surface the assumption.
    assert config.TOTAL_TOKEN_COUNT < 0.5 * config.MAX_TOKEN_COUNT, (
        "Test fixture invariant violated: this case must keep tokens below the "
        "secondary-pressure threshold to verify gating behavior."
    )


def _simulate_time_trigger_no_token_pressure(config, conversation, time_limit_seconds):
    """Trip the time trigger while keeping tokens below the secondary-pressure
    threshold. Used by the regression test for 'time trigger alone → no
    summarization'."""
    config.last_summary_time = 0
    current_time = 100000.0
    future_time = current_time + time_limit_seconds + 10
    config._fake_now = future_time
    # Token usage stays at the fixture default (~10 tokens for the seeded
    # system message), well below the secondary-pressure threshold.
    assert config.TOTAL_TOKEN_COUNT < 0.5 * config.MAX_TOKEN_COUNT, (
        "Test fixture invariant violated: this case must keep tokens below the "
        "secondary-pressure threshold to verify gating behavior."
    )


def _set_strictly_below_token_threshold(
    config, conversation, summarization_config, max_token_count, logger=None
):
    """
    Set token count to AT LEAST 5 tokens strictly below the threshold, AND
    keep conversation size at least 2 below its max size.
    Emit debug logs for threshold, target, and achieved values.
    Assert with diagnostic output if boundary is violated.
    """
    threshold_pct = summarization_config["triggers"]["token_threshold"]
    threshold_tokens = int(max_token_count * threshold_pct)
    conversation_max_size = getattr(config, "CONVERSATION_MAX_SIZE", 12)
    SAFE_MARGIN = 5
    # The max conversation length allowed for negative case
    max_conv_len = conversation_max_size - 2

    # Always keep system prompt
    conversation[:] = [{"role": "system", "content": "System prompt."}]

    # Compute how many user messages we can add without exceeding length limit
    # Each user message normally 10 tokens, but last one can be shorter if needed

    # Available message slots for user messages
    # system prompt occupies one
    available_slots = max_conv_len - 1  # minus system prompt

    # Maximum number of full 10-token user messages
    max_user_msgs = available_slots if available_slots > 0 else 0

    # Compute as we add N user messages of 10 tokens, what is token_count?
    base_token_count = count_message_tokens_always_10(conversation[0])
    needed_token_total = threshold_tokens - SAFE_MARGIN

    user_msg_tokens = 0
    user_msg_objs = []
    for i in range(max_user_msgs):
        current_total = base_token_count + user_msg_tokens + 10
        # If one more msg of 10 would exceed threshold, maybe make it a padding message
        if current_total > needed_token_total:
            break
        user_msg_objs.append({"role": "user", "content": f"Msg {i}"})
        user_msg_tokens += 10

    total_so_far = base_token_count + user_msg_tokens

    # If still room (in available_slots and not yet hit token total), try to add a final msg padded to just reach needed_token_total
    tokens_remaining = needed_token_total - total_so_far
    if tokens_remaining > 0 and len(user_msg_objs) < max_user_msgs:
        # Custom content so token counter yields tokens_remaining tokens (simulate - it's always 10 in this mock, so only possible if tokens_remaining == 10)
        # Let's only add it if exactly 10 is needed; else ignore (since count_message_tokens_always_10 always returns 10)
        if tokens_remaining == 10:
            user_msg_objs.append(
                {"role": "user", "content": f"Msg {len(user_msg_objs)}"}
            )
            user_msg_tokens += 10
            total_so_far = base_token_count + user_msg_tokens

    conversation.extend(user_msg_objs)

    config.TOTAL_TOKEN_COUNT = recount_conversation_tokens(
        conversation, count_message_tokens_always_10
    )

    if logger:
        logger.info(
            f"[NEGATIVE/Token] threshold={threshold_tokens}, margin={SAFE_MARGIN}, "
            f"set token_count={config.TOTAL_TOKEN_COUNT}, conv_len={len(conversation)}, "
            f"conv_max={conversation_max_size}, used_user_msgs={len(user_msg_objs)}, "
            f"needed_token_total={needed_token_total}, system_prompt_token={base_token_count}, "
            f"max_allowed_conv_len={max_conv_len}"
        )

    # Assert both boundaries
    assert config.TOTAL_TOKEN_COUNT <= threshold_tokens - SAFE_MARGIN and len(
        conversation
    ) <= conversation_max_size - 2, (
        f"Token or conversation size boundary violated: "
        f"threshold={threshold_tokens}, margin={SAFE_MARGIN}, got tokens={config.TOTAL_TOKEN_COUNT} "
        f"(must be <= {threshold_tokens-SAFE_MARGIN}), "
        f"conv_len={len(conversation)} (must be <= {conversation_max_size-2}), "
        f"conv_max={conversation_max_size}, needed_token_total={needed_token_total}, "
        f"used_user_msgs={len(user_msg_objs)}"
    )
    if logger:
        logger.info(
            f"Final negative-token setup: token_count={config.TOTAL_TOKEN_COUNT} (should be <= {threshold_tokens-SAFE_MARGIN}), "
            f"conv_len={len(conversation)} (should be <= {conversation_max_size-2})"
        )
    config.last_summary_time = 100000.0
    if hasattr(config, "_fake_now"):
        config._fake_now = 100000.0
    if logger:
        logger.info(
            f"Set negative-case time-neutral: last_summary_time={config.last_summary_time}, _fake_now={getattr(config, '_fake_now', None)}"
        )


def _set_strictly_below_conversation_size(
    config, conversation, conversation_max_size, logger=None
):
    """
    Set number of messages to at least 5 less than the maximum conversation size threshold.
    Emit debug logs for values.
    Assert with diagnostic output if violated.
    """
    SAFE_MARGIN = 5
    conversation[:] = [{"role": "system", "content": "System prompt."}]
    while len(conversation) < conversation_max_size - SAFE_MARGIN:
        m = {"role": "user", "content": f"Msg {len(conversation)}"}
        conversation.append(m)
    config.TOTAL_TOKEN_COUNT = recount_conversation_tokens(
        conversation, count_message_tokens_always_10
    )
    if logger:
        logger.info(
            f"[NEGATIVE/ConvSize] conv_max={conversation_max_size}, margin={SAFE_MARGIN}, set len={len(conversation)}"
        )
    assert len(conversation) <= conversation_max_size - SAFE_MARGIN, (
        f"Conversation size boundary violated: conv_max={conversation_max_size}, margin={SAFE_MARGIN}, got={len(conversation)}, token_count={config.TOTAL_TOKEN_COUNT}"
    )
    if logger:
        logger.info(
            f"Final negative-convsize setup: length={len(conversation)} (should be <= {conversation_max_size-SAFE_MARGIN}), token_count={config.TOTAL_TOKEN_COUNT}"
        )
    config.last_summary_time = 100000.0
    if hasattr(config, "_fake_now"):
        config._fake_now = 100000.0
    if logger:
        logger.info(
            f"Set negative-case time-neutral: last_summary_time={config.last_summary_time}, _fake_now={getattr(config, '_fake_now', None)}"
        )


def _set_strictly_below_time_trigger(config, conversation, time_limit_seconds):
    # Make last_summary_time very recent (now), so time since last summary < time_limit_seconds
    current_time = 100000.0
    config.last_summary_time = current_time
    config._fake_now = current_time + time_limit_seconds - 100
    # No edit needed to conversation


def _set_strictly_below_memory_trigger(
    config, conversation, memory_limit_mb, logger=None
):
    """
    Ensure conversation's memory usage is at least 10MB below the limit.
    Debug-log limit, margin and achieved values.
    Assert with diagnostic output if boundaries violated.
    """
    SAFE_MARGIN_MB = 10
    target_limit = int((memory_limit_mb * 1024 * 1024)) - (
        SAFE_MARGIN_MB * 1024 * 1024
    )
    # We'll fake __sizeof__ on the conversation to be at least 10MB less than needed.
    class SmallFakeList(list):
        def __sizeof__(self_inner):
            return target_limit

    conversation[:] = SmallFakeList(conversation)
    config.TOTAL_TOKEN_COUNT = recount_conversation_tokens(
        conversation, count_message_tokens_always_10
    )
    if logger:
        logger.info(
            f"[NEGATIVE/Memory] limit={memory_limit_mb} MB, safe_margin={SAFE_MARGIN_MB} MB, simulated_bytes={target_limit}"
        )
    assert target_limit <= int((memory_limit_mb * 1024 * 1024)) - (
        SAFE_MARGIN_MB * 1024 * 1024
    ), (
        f"Memory boundary violated: limit={memory_limit_mb}MB, margin={SAFE_MARGIN_MB}MB, simulated_bytes={target_limit}, conv_len={len(conversation)}"
    )
    if logger:
        logger.info(
            f"Final negative-memory setup: __sizeof__={target_limit} (should be <= {int((memory_limit_mb * 1024 * 1024)) - (SAFE_MARGIN_MB * 1024 * 1024)}), conv_len={len(conversation)}, tokens={config.TOTAL_TOKEN_COUNT}"
        )
    config.last_summary_time = 100000.0
    if hasattr(config, "_fake_now"):
        config._fake_now = 100000.0
    if logger:
        logger.info(
            f"Set negative-case time-neutral: last_summary_time={config.last_summary_time}, _fake_now={getattr(config, '_fake_now', None)}"
        )


# No additional code in this file.

# --- NEW TEST FOR PROMPT COUNT STALENESS AFTER SUMMARIZATION ---


def test_prompt_count_stale_after_summarization(logger, config, monkeypatch):
    """
    Surfacing bug: after summarization, prompt display using old conversation count is stale.
    """
    # Setup a conversation which will trigger summarization by exceeding max conversation size.
    conversation = [{"role": "system", "content": "System prompt."}] + [
        {"role": "user", "content": f"Message {i}"}
        for i in range(config.CONVERSATION_MAX_SIZE)
    ]
    config.TOTAL_TOKEN_COUNT = recount_conversation_tokens(
        conversation, count_message_tokens_always_10
    )

    monkeypatch.setattr(history, "count_message_tokens", count_message_tokens_always_10)
    monkeypatch.setattr(history, "update_token_usage", dummy_update_token_usage)
    # Set a dummy time to control summarization triggers.
    monkeypatch.setattr(time, "time", lambda: 1e6)

    # Secondary triggers (history-size / time / memory) now only contribute to
    # summarization when token pressure is also present. Bring the token count
    # above the secondary-pressure threshold so the conversation-size trigger
    # actually fires summarization in this test setup.
    _ensure_secondary_pressure(config, conversation)

    # Confirm we are over the conversation size trigger.
    limits = history.check_limits(
        config.TOTAL_TOKEN_COUNT,
        config.MAX_TOKEN_COUNT,
        config.CONVERSATION_MAX_SIZE,
        conversation,
        config.SUMMARIZATION_CONFIG,
        logger,
        config,
    )
    assert limits.get(
        "should_summarize", False
    ), "Test conversation should trigger summarization reset"

    system_prompt = next(
        (m["content"] for m in conversation if m["role"] == "system"),
        "System prompt.",
    )

    # Record original count (before summarization)
    old_count = len(conversation)

    # Patch LLM to simulate summary.
    with patch("monitor.core.llm.get_llm_completion") as mock_llm:
        mock_llm.return_value = fake_litellm_completion_func()
        summary_resp = mock_llm()

        def append_func(m, hist, count_func, update_func):
            count = count_message_tokens_always_10(m)
            hist.append(m)
            config.TOTAL_TOKEN_COUNT += count
            return count

        # set_token_count_func removed: function and argument
        history.reset_conversation_with_summary(
            summary=summary_resp.choices[0].message["content"],
            system_prompt=system_prompt,
            user_input="Resume input after summary.",
            conversation_history=conversation,
            append_func=append_func,
            logger=logger,
            config=config,
        )

    # After summarization, conversation is reset (truncated/condensed)
    new_count = len(conversation)

    # Simulate code bug: if someone keeps (caches) old_count, UI prompt is now stale.
    display_with_stale_count = format_prompt_display(
        conversation_count=old_count,
        tokens_remaining=config.MAX_TOKEN_COUNT - config.TOTAL_TOKEN_COUNT,
        cwd="/fakepath",
        model="gpt-test",
    )
    display_with_live_count = format_prompt_display(
        conversation_count=new_count,
        tokens_remaining=config.MAX_TOKEN_COUNT - config.TOTAL_TOKEN_COUNT,
        cwd="/fakepath",
        model="gpt-test",
    )
    # Test asserts to highlight the difference and bug
    assert (
        old_count != new_count
    ), "Summarization should change (usually shorten) the conversation length"
    assert display_with_stale_count != display_with_live_count, (
        "Prompt display is stale if the old length is reused after summarization; must use the up-to-date length"
    )
    # Commentary for bug explanation in assertion
    # Format note: when no compactions have fired this session, the H
    # indicator is "H:<count>" (no space, tight). After at least one
    # compaction, it becomes "H:<count> (N)" with the count suffixed.
    # These tests don't drive the counter, so we match the no-suffix form.
    assert (
        f"H:{old_count}" in display_with_stale_count
    ), "Display must show the old conversation count before summarization"
    assert (
        f"H:{new_count}" in display_with_live_count
    ), "Display must show the new conversation count after summarization"
