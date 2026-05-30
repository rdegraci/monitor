"""Tests for partial-preserve compaction helpers in monitor.lib.history.

Covers:
- _find_compaction_split_index: edge cases (empty, k<=0), boundary cases
  (exactly K user messages, K+1, K+N), and that the returned index is
  always a user-message boundary so tool_call/tool_result pairs aren't
  bisected.
- reset_conversation_with_partial_summary: correct post-reset shape, atomic
  swap, empty-preserved guard, MAX_TOKEN_COUNT overflow handling
  (truncation, abort), TOTAL_TOKEN_COUNT update.
"""

import logging
import types
from unittest.mock import MagicMock

import pytest

# Pre-import monitor.config to break a pre-existing import cycle between
# monitor.lib.history → monitor.config → monitor.core.llm_responses_adapter
# → monitor.lib.llm_utils → monitor.lib.history. When config loads first,
# the cycle resolves before history.py asks for it.
import monitor.config  # noqa: F401

from monitor.lib.history import (
    _find_compaction_split_index,
    reset_conversation_with_partial_summary,
)


# --- _find_compaction_split_index -------------------------------------------


def _msg(role, content="x"):
    return {"role": role, "content": content}


def test_split_index_returns_none_for_empty_history():
    assert _find_compaction_split_index([], 6) is None


def test_split_index_returns_none_for_zero_or_negative_k():
    history = [_msg("user", "1"), _msg("assistant", "1"), _msg("user", "2")]
    assert _find_compaction_split_index(history, 0) is None
    assert _find_compaction_split_index(history, -1) is None


def test_split_index_returns_none_when_user_count_lte_k():
    """When user-message count <= K, everything is already 'recent' — no
    portion to summarize, so compaction should skip."""
    history = [
        _msg("user", "1"), _msg("assistant", "r1"),
        _msg("user", "2"), _msg("assistant", "r2"),
        _msg("user", "3"), _msg("assistant", "r3"),
    ]
    # Exactly K user messages.
    assert _find_compaction_split_index(history, 3) is None
    # Fewer than K.
    assert _find_compaction_split_index(history, 5) is None


def test_split_index_returns_kth_to_last_user_message_index():
    """K+1 user messages, K=2: split at the index of the second-to-last
    user message (i.e., preserve last 2 user turns)."""
    history = [
        _msg("user", "1"), _msg("assistant", "r1"),  # 0, 1
        _msg("user", "2"), _msg("assistant", "r2"),  # 2, 3
        _msg("user", "3"), _msg("assistant", "r3"),  # 4, 5  <- preserve from here
        _msg("user", "4"), _msg("assistant", "r4"),  # 6, 7
    ]
    assert _find_compaction_split_index(history, 2) == 4


def test_split_index_with_larger_history():
    """K=6: with 10 user messages, split at the 5th user message index
    (preserving the last 6 user turns)."""
    history = []
    for i in range(10):
        history.append(_msg("user", f"u{i}"))
        history.append(_msg("assistant", f"a{i}"))
    # User messages are at indices 0, 2, 4, 6, 8, 10, 12, 14, 16, 18.
    # 6-th-to-last user index → user[10-6] = user[4] → index 8.
    assert _find_compaction_split_index(history, 6) == 8


def test_split_index_with_tool_call_chain_in_history():
    """The k-th-to-last user-message index respects whatever else is in
    history (assistant tool_calls, tool results, system). The returned
    index always points at a user message, so a tool_call/tool_result
    chain straddling it cannot be split mid-chain."""
    history = [
        _msg("system", "sys"),                              # 0
        _msg("user", "1"),                                  # 1
        {"role": "assistant", "tool_calls": [{"id": "t1"}]},  # 2
        {"role": "tool", "tool_call_id": "t1", "content": "ok"},  # 3
        _msg("assistant", "summary1"),                      # 4
        _msg("user", "2"),                                  # 5  <- preserve from here (K=2)
        _msg("assistant", "a2"),                            # 6
        _msg("user", "3"),                                  # 7
        _msg("assistant", "a3"),                            # 8
    ]
    assert _find_compaction_split_index(history, 2) == 5
    # The preserved portion starts with a user message — safe boundary.
    assert history[5]["role"] == "user"


def test_split_index_ignores_non_dict_entries_gracefully():
    """Defensive: malformed entries that aren't dicts shouldn't crash the
    indexer or be counted as user messages."""
    history = [
        "not-a-dict",
        _msg("user", "1"),
        None,
        _msg("user", "2"),
        _msg("user", "3"),
    ]
    # 3 well-formed user messages; K=1 means preserve only the last → split
    # at index 4.
    assert _find_compaction_split_index(history, 1) == 4


# --- reset_conversation_with_partial_summary --------------------------------


@pytest.fixture
def fake_config():
    cfg = types.SimpleNamespace()
    cfg.MAX_TOKEN_COUNT = 100_000
    cfg.TOTAL_TOKEN_COUNT = 0
    cfg.MODEL = "openai/gpt-5.4-mini"
    return cfg


def test_partial_reset_builds_expected_shape(fake_config, caplog):
    history = [
        _msg("user", "old-1"),
        _msg("assistant", "old-1-reply"),
        _msg("user", "recent-1"),
        _msg("assistant", "recent-1-reply"),
        _msg("user", "recent-2"),
    ]
    preserved = history[2:]
    caplog.set_level(logging.INFO)

    reset_conversation_with_partial_summary(
        summary="summary of old portion",
        system_prompt="SYS",
        preserved_messages=preserved,
        conversation_history=history,
        logger=logging.getLogger(__name__),
        config=fake_config,
    )

    assert history[0] == {"role": "system", "content": "SYS"}
    assert history[1] == {"role": "assistant", "content": "summary of old portion"}
    assert history[2:] == preserved


def test_partial_reset_with_empty_preserved_aborts(fake_config, caplog):
    """Calling with empty preserved_messages must NOT wipe history — that
    would silently drop everything. The function logs a warning and bails."""
    history = [_msg("user", "1"), _msg("assistant", "1")]
    snapshot = list(history)
    caplog.set_level(logging.WARNING)

    reset_conversation_with_partial_summary(
        summary="ignored",
        system_prompt="SYS",
        preserved_messages=[],
        conversation_history=history,
        logger=logging.getLogger(__name__),
        config=fake_config,
    )

    assert history == snapshot
    assert any("empty preserved_messages" in r.getMessage() for r in caplog.records)


def test_partial_reset_updates_total_token_count(fake_config):
    history = [
        _msg("user", "old"),
        _msg("user", "preserved"),
    ]
    preserved = history[1:]
    fake_config.TOTAL_TOKEN_COUNT = 999  # pre-existing value to be overwritten

    reset_conversation_with_partial_summary(
        summary="s",
        system_prompt="SYS",
        preserved_messages=preserved,
        conversation_history=history,
        logger=logging.getLogger(__name__),
        config=fake_config,
    )

    # After reset, TOTAL_TOKEN_COUNT should reflect the new (smaller) history.
    assert fake_config.TOTAL_TOKEN_COUNT > 0
    assert fake_config.TOTAL_TOKEN_COUNT != 999


def test_partial_reset_truncates_oversize_summary(fake_config, caplog, monkeypatch):
    """When proposed_total > MAX_TOKEN_COUNT, the summary should be
    truncated so the result fits. preserved_messages are non-negotiable —
    only the summary is the knob.

    The test conftest globally mocks litellm, which makes the real
    count_message_tokens return nonsense. Patch it with a char-length-based
    stub so the truncation branch is exercised with realistic ratios."""
    from monitor.lib import history as history_mod

    def stub_counter(msgs):
        # Mirror the ~4-chars-per-token heuristic the truncation logic in
        # history.py uses, so the stub's notion of "tokens" lines up with
        # the production code's char-to-token conversion.
        if isinstance(msgs, list):
            return sum(len(m.get("content", "") or "") for m in msgs if isinstance(m, dict)) // 4
        if isinstance(msgs, dict):
            return len(msgs.get("content", "") or "") // 4
        return 0

    monkeypatch.setattr(history_mod, "count_message_tokens", stub_counter)

    fake_config.MAX_TOKEN_COUNT = 1000  # tight budget
    preserved = [_msg("user", "short preserved")]
    history = [_msg("user", "old"), *preserved]
    # Summary much larger than the budget allows under stub counter
    # (100_000 chars > 1000).
    huge_summary = "x" * 100_000
    caplog.set_level(logging.WARNING)

    reset_conversation_with_partial_summary(
        summary=huge_summary,
        system_prompt="SYS",
        preserved_messages=preserved,
        conversation_history=history,
        logger=logging.getLogger(__name__),
        config=fake_config,
    )

    # Conversation should have been replaced, summary truncated.
    assert history[0]["role"] == "system"
    assert history[1]["role"] == "assistant"
    assert len(history[1]["content"]) < len(huge_summary)
    assert any("truncated to recover" in r.getMessage() for r in caplog.records)


def test_partial_reset_aborts_when_preserved_already_exceeds_budget(fake_config, caplog, monkeypatch):
    """If the preserved messages plus system prompt already exceed
    MAX_TOKEN_COUNT, there's no room for any summary. Must abort cleanly,
    leaving history unchanged, rather than corrupt the conversation."""
    from monitor.lib import history as history_mod

    def stub_counter(msgs):
        # Mirror the ~4-chars-per-token heuristic the truncation logic in
        # history.py uses, so the stub's notion of "tokens" lines up with
        # the production code's char-to-token conversion.
        if isinstance(msgs, list):
            return sum(len(m.get("content", "") or "") for m in msgs if isinstance(m, dict)) // 4
        if isinstance(msgs, dict):
            return len(msgs.get("content", "") or "") // 4
        return 0

    monkeypatch.setattr(history_mod, "count_message_tokens", stub_counter)

    fake_config.MAX_TOKEN_COUNT = 50  # absurdly small
    preserved = [_msg("user", "x" * 5000)]  # blows past 50 chars easily
    history = [_msg("user", "old"), *preserved]
    snapshot = list(history)
    caplog.set_level(logging.CRITICAL)

    reset_conversation_with_partial_summary(
        summary="any summary",
        system_prompt="SYS",
        preserved_messages=preserved,
        conversation_history=history,
        logger=logging.getLogger(__name__),
        config=fake_config,
    )

    # History must be left untouched — no partial state.
    assert history == snapshot
    assert any("Aborting reset" in r.getMessage() for r in caplog.records)
