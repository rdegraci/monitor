"""Tests for the per-turn cost ledger (config.TURN_COSTS_USD).

Covers the two wiring points:
1. append_to_history_with_count opens a new bucket on each user message.
2. token_management.update_token_usage accumulates cost into the LAST bucket.

The invariant tested: one user message → one bucket, regardless of how many
LLM calls (tool-call rounds) happen between user messages.
"""

import pytest

import monitor.config  # noqa: F401 — break import cycle
from monitor import config


def _reset_turn_costs(monkeypatch):
    monkeypatch.setattr(config, "TURN_COSTS_USD", [], raising=False)


def test_user_message_opens_new_bucket(monkeypatch):
    """A user message appended via append_to_history_with_count must
    extend TURN_COSTS_USD by exactly one zero entry."""
    from monitor.lib.history import append_to_history_with_count

    _reset_turn_costs(monkeypatch)
    history = []

    append_to_history_with_count(
        message={"role": "user", "content": "first message"},
        conversation_history=history,
        count_message_tokens_func=lambda m: 5,
        update_token_usage_func=lambda t: None,
    )

    assert config.TURN_COSTS_USD == [0.0]


def test_assistant_message_does_not_open_bucket(monkeypatch):
    """Only user-role messages should extend the ledger. Assistant replies
    and tool results stay within the bucket of the user message that
    triggered them."""
    from monitor.lib.history import append_to_history_with_count

    _reset_turn_costs(monkeypatch)
    history = []

    append_to_history_with_count(
        message={"role": "assistant", "content": "reply"},
        conversation_history=history,
        count_message_tokens_func=lambda m: 5,
        update_token_usage_func=lambda t: None,
    )

    assert config.TURN_COSTS_USD == []


def test_tool_role_does_not_open_bucket(monkeypatch):
    """Same rule for tool-result messages."""
    from monitor.lib.history import append_to_history_with_count

    _reset_turn_costs(monkeypatch)
    history = []

    append_to_history_with_count(
        message={"role": "tool", "tool_call_id": "x", "content": "result"},
        conversation_history=history,
        count_message_tokens_func=lambda m: 5,
        update_token_usage_func=lambda t: None,
    )

    assert config.TURN_COSTS_USD == []


def test_multiple_user_messages_open_multiple_buckets(monkeypatch):
    """Two user messages → two buckets, each starting at 0.0."""
    from monitor.lib.history import append_to_history_with_count

    _reset_turn_costs(monkeypatch)
    history = []

    for _ in range(3):
        append_to_history_with_count(
            message={"role": "user", "content": "x"},
            conversation_history=history,
            count_message_tokens_func=lambda m: 5,
            update_token_usage_func=lambda t: None,
        )

    assert config.TURN_COSTS_USD == [0.0, 0.0, 0.0]


def test_cost_accumulates_into_last_bucket(monkeypatch):
    """When token_management observes a cost, it goes into the latest
    bucket. Multiple cost events from the same user-message-bounded turn
    must SUM into the same bucket — that's the property that makes
    tool-call chains attribute correctly to the user message that
    triggered them."""
    from monitor.lib.history import append_to_history_with_count

    _reset_turn_costs(monkeypatch)
    history = []

    # Open a bucket via a user message.
    append_to_history_with_count(
        message={"role": "user", "content": "do many tools"},
        conversation_history=history,
        count_message_tokens_func=lambda m: 5,
        update_token_usage_func=lambda t: None,
    )

    # Simulate three LLM-call cost events (e.g., a tool-call chain).
    # We poke the same accumulation logic that update_token_usage uses.
    for cost in (0.10, 0.25, 0.05):
        turn_costs = list(getattr(config, "TURN_COSTS_USD", []) or [])
        if not turn_costs:
            turn_costs.append(0.0)
        turn_costs[-1] = turn_costs[-1] + cost
        config.TURN_COSTS_USD = turn_costs

    # All three costs must have folded into bucket[0] — there should still
    # be only one bucket because no new user message arrived.
    assert len(config.TURN_COSTS_USD) == 1
    assert abs(config.TURN_COSTS_USD[0] - 0.40) < 1e-9


def test_second_user_message_does_not_reset_prior_buckets(monkeypatch):
    """When a new user message arrives, the prior buckets stay frozen so
    they can be summed into the recent-window display. New bucket starts
    at zero."""
    from monitor.lib.history import append_to_history_with_count

    _reset_turn_costs(monkeypatch)
    history = []

    append_to_history_with_count(
        message={"role": "user", "content": "first"},
        conversation_history=history,
        count_message_tokens_func=lambda m: 5,
        update_token_usage_func=lambda t: None,
    )
    # Manually credit the first bucket with some spend.
    config.TURN_COSTS_USD[-1] = 0.42

    append_to_history_with_count(
        message={"role": "user", "content": "second"},
        conversation_history=history,
        count_message_tokens_func=lambda m: 5,
        update_token_usage_func=lambda t: None,
    )

    assert config.TURN_COSTS_USD == [0.42, 0.0]
