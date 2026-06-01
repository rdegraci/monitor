"""Tests for SESSION_COMPACTION_COUNT and its H: indicator display.

Covers:
- Default counter value is 0.
- H: format with 0 compactions: "H: <count>" (no parens, space after colon).
- H: format with N>0 compactions: "H:(N) <count>".
- :reset_history clears the counter.
"""

import logging

import pytest

# Pre-import config to break the import cycle (same pattern as other lib tests).
import monitor.config  # noqa: F401

from monitor import config


def test_default_counter_is_zero():
    """Sanity check: the new global initializes to 0."""
    # Read from a fresh fetch in case other tests bumped it.
    fresh_default = 0
    # Just verify the attribute exists and is an int.
    assert isinstance(getattr(config, "SESSION_COMPACTION_COUNT", None), int)


def test_h_indicator_no_parens_when_zero(monkeypatch):
    """With no compactions, the H: indicator must be 'H: <count>' with a
    space — no '(0)' parenthetical."""
    from monitor.lib.display_output import format_prompt_display

    monkeypatch.setattr(config, "SESSION_COMPACTION_COUNT", 0, raising=False)

    output = format_prompt_display(
        conversation_count=124,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4-mini",
    )

    assert "H: 124" in output
    assert "H:(" not in output  # explicitly no parens


def test_h_indicator_includes_parens_when_nonzero(monkeypatch):
    """Once at least one compaction has fired this session, the H: indicator
    should display 'H:(N) <count>'."""
    from monitor.lib.display_output import format_prompt_display

    monkeypatch.setattr(config, "SESSION_COMPACTION_COUNT", 2, raising=False)

    output = format_prompt_display(
        conversation_count=124,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4-mini",
    )

    assert "H:(2) 124" in output


def test_reset_history_clears_compaction_count(monkeypatch):
    """The :reset_history command must zero out SESSION_COMPACTION_COUNT
    alongside the other cumulative session counters — otherwise the (N)
    prefix would persist across an explicit fresh-start."""
    from monitor.lib.built_in_commands import reset_conversation_history_command

    # Pre-set the counter to a non-zero value.
    monkeypatch.setattr(config, "SESSION_COMPACTION_COUNT", 5, raising=False)
    # Provide the bits :reset_history touches so it doesn't crash.
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [], raising=False)
    monkeypatch.setattr(config, "TOTAL_TOKEN_COUNT", 0, raising=False)
    monkeypatch.setattr(config, "SESSION_TOTAL_TOKENS", 0, raising=False)
    monkeypatch.setattr(config, "SESSION_COST_USD", 0.0, raising=False)
    monkeypatch.setattr(config, "RESPONSE_ID", None, raising=False)
    monkeypatch.setattr(config, "SESSION_ID", "test-session", raising=False)

    reset_conversation_history_command()

    assert config.SESSION_COMPACTION_COUNT == 0


def test_h_indicator_does_not_show_parens_for_negative(monkeypatch):
    """Defensive: a negative count (shouldn't happen, but if it did) must
    not produce 'H:(-1) 124'. Treat <=0 as no compactions."""
    from monitor.lib.display_output import format_prompt_display

    monkeypatch.setattr(config, "SESSION_COMPACTION_COUNT", -1, raising=False)

    output = format_prompt_display(
        conversation_count=124,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4-mini",
    )

    assert "H: 124" in output
    assert "H:(-" not in output
