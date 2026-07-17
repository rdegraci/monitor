"""Tests for status-line modes and session hygiene (PLAN Phase 6)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from monitor.core.built_ins import configure_built_ins
from monitor.core.conversation import compute_prompt_display
from monitor.lib import display_output
from monitor.lib.built_ins_utils import execute_built_in_function
from monitor.lib.status_line import (
    DEFAULT_STATUS_LINE_MODE,
    compaction_recovery_notice,
    filter_status_segments,
    get_status_line_mode,
    print_cliff_streak_warning_if_needed,
    reset_cliff_warning_state,
    set_status_line_mode,
    status_line_command,
)


@pytest.fixture(autouse=True)
def _restore_status_mode():
    original = get_status_line_mode()
    yield
    set_status_line_mode(original)


def test_default_mode_is_coding():
    set_status_line_mode(DEFAULT_STATUS_LINE_MODE)
    assert get_status_line_mode() == "coding"


def test_set_status_line_mode_validates():
    assert set_status_line_mode("debug") == "debug"
    assert set_status_line_mode("unknown") == "coding"


def test_filter_status_segments_by_mode():
    segments = [
        ("F", "1"),
        ("C", "2"),
        ("R", "3"),
        ("U", "4"),
        ("L", "5"),
        ("H", "6"),
        ("RT", "7"),
    ]
    assert filter_status_segments(segments, "minimal") == ["H:6", "C:2"]
    assert filter_status_segments(segments, "coding") == [
        "H:6",
        "C:2",
        "U:4",
        "F:1",
    ]
    assert filter_status_segments(segments, "debug") == [
        "F:1",
        "C:2",
        "R:3",
        "U:4",
        "L:5",
        "H:6",
        "RT:7",
    ]


def test_format_prompt_display_coding_hides_debug_fields():
    with patch.object(display_output.config, "STATUS_LINE_MODE", "coding", create=True), patch.object(
        display_output.config, "SESSION_COST_USD", 1.25, create=True
    ), patch.object(display_output.config, "SHOW_COST_ESTIMATE", True, create=True), patch.object(
        display_output.config, "SESSION_TOTAL_TOKENS", 100, create=True
    ), patch.object(display_output.config, "LAST_REQUEST_TOKEN_COUNT", 42, create=True), patch.object(
        display_output.config, "TURN_ROUND_TRIPS", [3], create=True
    ):
        result = display_output.format_prompt_display(
            conversation_count=2,
            tokens_remaining=500,
            context_remaining=500,
            context_budget=1000,
            total_used=100,
            last_used=42,
            cwd="/tmp",
            model="gpt-test",
        )

    assert "H:2" in result
    assert "C:" in result
    assert "U:" in result
    assert "~T:$" in result
    assert "R:" not in result
    assert "L:" not in result
    assert "RT:" not in result
    assert "Cache " not in result


def test_format_prompt_display_minimal_shows_cliff_percent_only():
    with patch.object(display_output.config, "STATUS_LINE_MODE", "minimal", create=True), patch.object(
        display_output.config, "LAST_BILLED_INPUT_TOKENS", 100000, create=True
    ), patch.object(display_output.config, "RESPONSES_CHAIN_TIER_TOKENS", 128000, create=True):
        result = display_output.format_prompt_display(
            conversation_count=4,
            tokens_remaining=900000,
            context_remaining=900000,
            context_budget=922000,
            total_used=999,
            last_used=10,
            cwd="/tmp",
        )

    assert "H:4" in result
    assert "78%" in result
    assert "U:" not in result
    assert "F:" not in result
    assert "100000" not in result


def test_format_prompt_display_debug_keeps_full_fields():
    with patch.object(display_output.config, "STATUS_LINE_MODE", "debug", create=True), patch.object(
        display_output.config, "LAST_REQUEST_TOKEN_COUNT", 99, create=True
    ), patch.object(display_output.config, "TURN_ROUND_TRIPS", [2], create=True):
        result = display_output.format_prompt_display(
            conversation_count=1,
            tokens_remaining=800,
            context_remaining=800,
            context_budget=1000,
            rate_remaining=5000,
            total_used=50,
            last_used=99,
            cwd="/tmp",
        )

    assert "R:" in result
    assert "L:" in result
    assert "RT:2" in result


def test_status_command_shows_and_sets_mode(capsys):
    configure_built_ins()
    execute_built_in_function(":status")
    out = capsys.readouterr().out
    assert "Status-line mode:" in out

    execute_built_in_function(":status debug")
    out = capsys.readouterr().out
    assert "debug" in out
    assert get_status_line_mode() == "debug"


def test_compaction_recovery_notice_includes_recovery_commands():
    text = compaction_recovery_notice()
    assert ":break_chain" in text
    assert ":compact" in text
    assert ":reset_history" in text


def test_cliff_streak_warning_prints_once_per_level(capsys):
    reset_cliff_warning_state()
    with patch.object(display_output.config, "SESSION_TURNS_OVER_CLIFF", 3, create=True), patch.object(
        display_output.config, "RESPONSES_CHAIN_TIER_TOKENS", 128000, create=True
    ):
        print_cliff_streak_warning_if_needed()
        print_cliff_streak_warning_if_needed()
    out = capsys.readouterr().out
    assert out.count("[notice]") == 1
    assert ":break_chain" in out


def test_compute_prompt_display_emits_cliff_warning(capsys):
    reset_cliff_warning_state()
    configure_built_ins()
    with patch(
        "monitor.core.conversation.count_message_tokens",
        return_value=100,
    ), patch.object(display_output.config, "SESSION_TURNS_OVER_CLIFF", 4, create=True), patch.object(
        display_output.config, "RESPONSES_CHAIN_TIER_TOKENS", 128000, create=True
    ), patch.object(
        display_output.config, "CONVERSATION_HISTORY", [{"role": "user", "content": "hi"}], create=True
    ), patch.object(display_output.config, "MODEL_INPUT_WINDOW", 1000, create=True), patch.object(
        display_output.config, "MAX_TOKEN_COUNT", 1000, create=True
    ):
        compute_prompt_display()
    out = capsys.readouterr().out
    assert "2x cost cliff" in out
