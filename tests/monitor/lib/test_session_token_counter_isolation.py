"""Regression tests for the SESSION_TOTAL_TOKENS / LAST_REQUEST_TOKEN_COUNT
isolation between local history appends and actual LLM-call accounting.

Before the fix:
  - append_to_history_with_count → update_token_usage → SESSION_TOTAL_TOKENS
    and LAST_REQUEST_TOKEN_COUNT inflated for local appends (no API call).
  - At startup with just the system message in history, U: showed ~7K
    tokens instead of 0; L: showed the same value instead of None/0.

After the fix:
  - append_to_history_with_count → update_history_token_count
    → updates ONLY TOTAL_TOKEN_COUNT (history-size counter).
  - SESSION_TOTAL_TOKENS and LAST_REQUEST_TOKEN_COUNT remain at their
    initial values until an LLM-call return path invokes update_token_usage.
"""

import pytest

import monitor.config  # noqa: F401 — break import cycle
from monitor import config
from monitor.lib.history import append_to_history_with_count
from monitor.lib.token_management import update_history_token_count, update_token_usage


@pytest.fixture(autouse=True)
def _reset_counters(monkeypatch):
    monkeypatch.setattr(config, "TOTAL_TOKEN_COUNT", 0, raising=False)
    monkeypatch.setattr(config, "SESSION_TOTAL_TOKENS", 0, raising=False)
    monkeypatch.setattr(config, "SESSION_COST_USD", 0.0, raising=False)
    monkeypatch.setattr(config, "TURN_COSTS_USD", [], raising=False)
    monkeypatch.setattr(config, "LAST_REQUEST_TOKEN_COUNT", None, raising=False)
    monkeypatch.setattr(config, "LAST_REQUEST_USED_ESTIMATE", False, raising=False)
    yield


def test_history_append_does_not_inflate_session_total_tokens():
    """The headline regression: appending a 7000-token system message at
    startup should leave SESSION_TOTAL_TOKENS at 0, not 7000."""
    conversation_history = []
    fake_count = lambda msg: 7000
    fake_update_legacy = lambda n: None  # no-op; the new code ignores this

    append_to_history_with_count(
        {"role": "system", "content": "fake big system prompt"},
        conversation_history,
        fake_count,
        fake_update_legacy,
    )

    assert config.SESSION_TOTAL_TOKENS == 0
    # TOTAL_TOKEN_COUNT still tracks history size — it's used by compaction
    # triggers — so it should reflect the appended message.
    assert config.TOTAL_TOKEN_COUNT == 7000


def test_history_append_does_not_inflate_last_request_token_count():
    """LAST_REQUEST_TOKEN_COUNT must stay None/0 until an actual LLM
    request has completed. Local appends shouldn't touch it."""
    conversation_history = []

    append_to_history_with_count(
        {"role": "user", "content": "hi"},
        conversation_history,
        lambda msg: 25,
        lambda n: None,
    )

    # No LLM call → no last-request count.
    assert config.LAST_REQUEST_TOKEN_COUNT is None


def test_llm_call_path_still_updates_session_tokens_and_last_request():
    """The other side of the invariant: when update_token_usage IS called
    (from the LLM-return path with the real request size), all the counters
    update together. This is the *legitimate* accounting path."""
    update_token_usage(1234, used_estimate=False)

    assert config.SESSION_TOTAL_TOKENS == 1234
    assert config.TOTAL_TOKEN_COUNT == 1234
    assert config.LAST_REQUEST_TOKEN_COUNT == 1234


def test_full_turn_does_not_double_count_tokens():
    """End-to-end check for the double-count bug. A single user turn:
      1. user message appended         → +25 TOTAL only
      2. LLM responds with 500 tokens  → +500 SESSION_TOTAL + 500 TOTAL
      3. assistant message appended    → +50 TOTAL only (response-as-text)

    SESSION_TOTAL_TOKENS should be exactly 500 (the LLM's reported usage),
    NOT 25 + 500 + 50 = 575 (the buggy double-counted value)."""
    conversation_history = []

    # User message appended locally.
    append_to_history_with_count(
        {"role": "user", "content": "hi"}, conversation_history,
        lambda msg: 25, lambda n: None,
    )

    # LLM call returns; the call-site reports actual provider usage.
    update_token_usage(500, used_estimate=False)

    # Assistant message gets appended after the LLM responds.
    append_to_history_with_count(
        {"role": "assistant", "content": "hello"}, conversation_history,
        lambda msg: 50, lambda n: None,
    )

    # SESSION_TOTAL_TOKENS tracks API consumption only.
    assert config.SESSION_TOTAL_TOKENS == 500
    # TOTAL_TOKEN_COUNT tracks current history size (cumulative through
    # the lifetime of the conversation: 25 user + 500 LLM-reported usage + 50 assistant).
    assert config.TOTAL_TOKEN_COUNT == 575
