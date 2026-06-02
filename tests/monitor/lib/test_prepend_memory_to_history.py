"""Tests for the prepend_memory_to_history overwrite-bug fix.

Pre-fix: when CONVERSATION_HISTORY was non-empty, the function did
``CONVERSATION_HISTORY[0] = memory_dict``, silently overwriting the
platform system prompt with a memory entry on every call.

Post-fix: existing memory entries (recognized by their content marker)
are replaced in place; new memory entries are inserted AFTER the system
prompt at index 1 (or at index 0 if history is empty).
"""

import pytest
from unittest.mock import patch, MagicMock

import monitor.config  # noqa: F401 — break import cycle
from monitor import config


@pytest.fixture(autouse=True)
def _isolated_history(monkeypatch):
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [], raising=False)
    yield


def _system(content):
    return {"role": "system", "content": content}


def _patch_redis_for_memory(monkeypatch, memory_entries):
    """Make get_redis_client / fetch_memory_for_context return a controlled
    set of memory entries so the test can drive prepend_memory_to_history's
    has-memory branch deterministically."""
    from monitor.lib import redis_utils

    monkeypatch.setattr(config, "MEMORY_SERVICES", True, raising=False)

    fake_client = MagicMock()
    fake_client.get.side_effect = lambda key: (
        f'{{"user_input": "input-{key}", "response": "resp-{key}"}}'
        if key in memory_entries else None
    )
    monkeypatch.setattr(redis_utils, "get_redis_client", lambda: fake_client)
    monkeypatch.setattr(redis_utils, "fetch_memory_for_context", lambda: memory_entries)
    monkeypatch.setattr(redis_utils, "verify_ttl", lambda key: (True, 3600))


def test_system_prompt_at_index_0_is_preserved(monkeypatch):
    """Regression: the platform system prompt at index 0 must NOT be
    clobbered when memory is prepended."""
    from monitor.lib.redis_utils import prepend_memory_to_history

    config.CONVERSATION_HISTORY[:] = [
        _system("PLATFORM_SYSTEM_PROMPT_DO_NOT_LOSE"),
        {"role": "user", "content": "hi"},
    ]
    _patch_redis_for_memory(monkeypatch, ["k1"])

    prepend_memory_to_history()

    # Platform system prompt must still be at index 0.
    assert config.CONVERSATION_HISTORY[0]["role"] == "system"
    assert "PLATFORM_SYSTEM_PROMPT_DO_NOT_LOSE" in config.CONVERSATION_HISTORY[0]["content"]
    # Memory entry must have been inserted (not at index 0).
    assert any(
        isinstance(m, dict)
        and m.get("role") == "system"
        and isinstance(m.get("content"), str)
        and m["content"].startswith("Previous conversation context:")
        for m in config.CONVERSATION_HISTORY
    )


def test_memory_inserted_after_system_prompt(monkeypatch):
    """The new memory entry should land at index 1 (immediately after the
    platform system prompt), not anywhere else."""
    from monitor.lib.redis_utils import prepend_memory_to_history

    config.CONVERSATION_HISTORY[:] = [
        _system("PLATFORM"),
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    _patch_redis_for_memory(monkeypatch, ["k1"])

    prepend_memory_to_history()

    assert config.CONVERSATION_HISTORY[1]["role"] == "system"
    assert config.CONVERSATION_HISTORY[1]["content"].startswith("Previous conversation context:")
    # Length grew by exactly 1 — no duplicates.
    assert len(config.CONVERSATION_HISTORY) == 4


def test_repeated_calls_do_not_grow_history(monkeypatch):
    """Calling prepend_memory_to_history twice must not produce two memory
    entries. The second call finds the existing entry and replaces it in
    place. This is critical: prepare_query_context invokes this on every
    user turn, and unbounded growth would leak memory entries into context."""
    from monitor.lib.redis_utils import prepend_memory_to_history

    config.CONVERSATION_HISTORY[:] = [
        _system("PLATFORM"),
        {"role": "user", "content": "hi"},
    ]
    _patch_redis_for_memory(monkeypatch, ["k1"])

    prepend_memory_to_history()
    len_after_first = len(config.CONVERSATION_HISTORY)
    prepend_memory_to_history()
    len_after_second = len(config.CONVERSATION_HISTORY)

    assert len_after_first == len_after_second
    # Exactly one memory entry in history.
    memory_count = sum(
        1 for m in config.CONVERSATION_HISTORY
        if isinstance(m, dict)
        and m.get("role") == "system"
        and isinstance(m.get("content"), str)
        and m["content"].startswith("Previous conversation context:")
    )
    assert memory_count == 1


def test_empty_history_insert_at_index_0(monkeypatch):
    """If history is completely empty (no system prompt yet), the memory
    entry goes at index 0 — there's nothing to land after."""
    from monitor.lib.redis_utils import prepend_memory_to_history

    config.CONVERSATION_HISTORY[:] = []
    _patch_redis_for_memory(monkeypatch, ["k1"])

    prepend_memory_to_history()

    assert len(config.CONVERSATION_HISTORY) == 1
    assert config.CONVERSATION_HISTORY[0]["content"].startswith("Previous conversation context:")


def test_memory_content_updates_replace_in_place(monkeypatch):
    """When the underlying memory entries change between calls, the
    existing in-history memory message gets its content replaced — not
    appended to."""
    from monitor.lib.redis_utils import prepend_memory_to_history

    config.CONVERSATION_HISTORY[:] = [_system("PLATFORM")]

    # First call seeds an entry with key k1.
    _patch_redis_for_memory(monkeypatch, ["k1"])
    prepend_memory_to_history()

    first_memory = config.CONVERSATION_HISTORY[1]["content"]
    assert "input-k1" in first_memory

    # Second call returns a different set of keys; the in-history memory
    # message should reflect the new content, not concatenate.
    _patch_redis_for_memory(monkeypatch, ["k2"])
    prepend_memory_to_history()

    new_memory = config.CONVERSATION_HISTORY[1]["content"]
    assert "input-k2" in new_memory
    assert "input-k1" not in new_memory  # replaced, not appended
    assert len(config.CONVERSATION_HISTORY) == 2  # length unchanged
