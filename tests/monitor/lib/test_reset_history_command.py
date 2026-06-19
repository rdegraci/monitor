"""Tests for :reset_history matching the startup state.

After reset, the conversation history and session-scoped state should look
exactly like a freshly-started app sitting at the ready-for-first-input
prompt. Two specific behaviors verified here:

1. The project-instructions content cache is cleared so the rebuilt
   system prompt re-reads MONITOR.md / MONITOR_CONVENTIONS.md from disk.
   This lets a user edit those files mid-session and have :reset_history
   pick up the new content without restarting.

2. config.last_summary_time is reset to the current time, so the
   time-based summarization secondary trigger starts fresh (matches
   startup, which also sets this).
"""

import time

import pytest

import monitor.config  # noqa: F401 — break import cycle
from monitor import config
from monitor.lib import built_in_commands
from monitor.lib import system_prompt


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch):
    """Each test gets a clean slate. Restore cwd-override paths after."""
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [], raising=False)
    monkeypatch.setattr(config, "TOTAL_TOKEN_COUNT", 0, raising=False)
    monkeypatch.setattr(config, "SESSION_TOTAL_TOKENS", 0, raising=False)
    monkeypatch.setattr(config, "SESSION_COST_USD", 0.0, raising=False)
    monkeypatch.setattr(config, "SESSION_COMPACTION_COUNT", 0, raising=False)
    monkeypatch.setattr(config, "TURN_COSTS_USD", [], raising=False)
    monkeypatch.setattr(config, "CURRENT_TURN_REASONING_OVERRIDE", None, raising=False)
    monkeypatch.setattr(config, "RESPONSE_ID", None, raising=False)
    monkeypatch.setattr(config, "PROJECT_INSTRUCTIONS_CONTENT", None, raising=False)
    monkeypatch.setattr(config, "SESSION_ID", "test-session", raising=False)
    yield
    system_prompt.configure_runtime_prompt_paths(None)
    system_prompt.clear_project_instructions_cache()


def test_reset_history_re_reads_project_instructions_from_disk(tmp_path):
    """The user edits MONITOR.md mid-session, runs :reset_history, and the
    new content shows up in the rebuilt system prompt. Without the
    cache-clear, the stale content would persist."""
    (tmp_path / "MONITOR.md").write_text("FIRST_VERSION_OF_MONITOR\n")
    (tmp_path / "MONITOR_CONVENTIONS.md").write_text("CONV_V1\n")
    system_prompt.configure_runtime_prompt_paths(tmp_path)

    # Initial state: history has the first MONITOR content baked in.
    initial = system_prompt.build_system_prompt(session_id="test-session")
    assert "FIRST_VERSION_OF_MONITOR" in initial

    # User edits MONITOR.md mid-session.
    (tmp_path / "MONITOR.md").write_text("SECOND_VERSION_OF_MONITOR\n")

    # Reset history — should pick up the edit.
    built_in_commands.reset_conversation_history_command()

    assert len(config.CONVERSATION_HISTORY) == 1
    new_system_msg = config.CONVERSATION_HISTORY[0]["content"]
    assert "SECOND_VERSION_OF_MONITOR" in new_system_msg
    assert "FIRST_VERSION_OF_MONITOR" not in new_system_msg


def test_reset_history_updates_last_summary_time():
    """Startup sets config.last_summary_time = time.time(). Reset should
    too — otherwise the time-based summarization secondary trigger uses
    a stale timestamp and may fire spuriously on the next turn."""
    # Simulate an old "last summary" timestamp from a long-running session.
    config.last_summary_time = time.time() - 100_000  # ~28 hours ago

    built_in_commands.reset_conversation_history_command()

    elapsed_since_reset = time.time() - config.last_summary_time
    # Should be a very small number — same as if startup had just run.
    assert elapsed_since_reset < 1.0


def test_reset_history_clears_session_counters():
    """Regression: all session-scoped state should zero out so the indicator
    in the prompt line restarts from a clean baseline."""
    config.SESSION_COST_USD = 5.42
    config.SESSION_TOTAL_TOKENS = 123456
    config.SESSION_COMPACTION_COUNT = 3
    config.TURN_COSTS_USD = [0.1, 0.2, 0.3]
    config.CURRENT_TURN_REASONING_OVERRIDE = "high"
    config.RESPONSE_ID = "stale-response-id"
    # The per-model calibration store that feeds :fuel_debug must also clear,
    # else a fresh T:/U: would be mixed against stale composition/effort data.
    config.SESSION_CALIBRATION_BY_MODEL = {
        "openai/gpt-5.4": {"cost_usd": 1.0, "total_tokens": 35_000},
    }

    built_in_commands.reset_conversation_history_command()

    assert config.SESSION_COST_USD == 0.0
    assert config.SESSION_TOTAL_TOKENS == 0
    assert config.SESSION_COMPACTION_COUNT == 0
    assert config.TURN_COSTS_USD == []
    assert config.CURRENT_TURN_REASONING_OVERRIDE is None
    assert config.RESPONSE_ID is None
    assert config.SESSION_CALIBRATION_BY_MODEL == {}


def test_reset_history_produces_single_system_message():
    """After reset, history must be exactly [{system_message}] — same shape
    as initialize_chat_history at startup."""
    # Pollute history with some prior content.
    config.CONVERSATION_HISTORY[:] = [
        {"role": "system", "content": "old system"},
        {"role": "user", "content": "old user"},
        {"role": "assistant", "content": "old assistant"},
    ]

    built_in_commands.reset_conversation_history_command()

    assert len(config.CONVERSATION_HISTORY) == 1
    assert config.CONVERSATION_HISTORY[0]["role"] == "system"
