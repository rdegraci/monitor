"""Tests for the labeled three-slot cost annotation in the U: indicator.

The U: indicator now shows: ``U:<tokens> (~T:$total W:$window P:$previous)``
where:
- T = Total (cumulative SESSION_COST_USD; tilde marks it as an estimate)
- W = Window sum over the last RECENT_TURN_WINDOW (default 10) buckets
- P = Previous turn (most recently completed bucket = TURN_COSTS_USD[-1])

Slots collapse when they carry no new information:
- W is suppressed when its value matches T within half a cent (the early-session
  case where all buckets still fit inside the window).
- P is suppressed when the most recent bucket is $0 (litellm couldn't price
  the call, or the bucket survived a refusal without ever receiving a cost).

Labels — instead of bare-dollar slots — make collapses unambiguous: when W
is gone you can still tell P apart from T at a glance, which the previous
positional layout couldn't.
"""

import re

import pytest

import monitor.config  # noqa: F401 — break import cycle
from monitor import config
from monitor.lib.display_output import format_prompt_display


def _set_cost_state(monkeypatch, *, cost, turn_costs, show=True):
    monkeypatch.setattr(config, "SHOW_COST_ESTIMATE", show, raising=False)
    monkeypatch.setattr(config, "SESSION_COST_USD", cost, raising=False)
    monkeypatch.setattr(config, "TURN_COSTS_USD", turn_costs, raising=False)
    monkeypatch.setattr(config, "RECENT_TURN_WINDOW", 10, raising=False)


# --- Three-slot format -------------------------------------------------------


def test_three_value_format_when_all_slots_meaningful(monkeypatch):
    """11 priced buckets at $1 each → cumulative=$11, window=$10 (last 10),
    previous=$1. All three slots distinct and shown with labels."""
    turn_costs = [1.0] * 11
    _set_cost_state(monkeypatch, cost=sum(turn_costs), turn_costs=turn_costs)

    output = format_prompt_display(
        conversation_count=11,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4",
        total_used=1_000_000,
    )

    match = re.search(r"\(~T:\$([0-9.]+) W:\$([0-9.]+) P:\$([0-9.]+)\)", output)
    assert match, f"Expected ~T:$x W:$y P:$z format, got: {output}"
    total, window, prev = (float(x) for x in match.groups())
    assert abs(total - 11.0) < 0.01
    assert abs(window - 10.0) < 0.01
    assert abs(prev - 1.0) < 0.01


def test_previous_sub_dollar_uses_four_decimals(monkeypatch):
    """Cheap turns shouldn't visually round to $0.00 — 4 decimals on P:
    keeps fractions of a cent legible. T: (cumulative) uses 3 decimals
    under $1."""
    _set_cost_state(monkeypatch, cost=0.005, turn_costs=[0.001, 0.002, 0.002])

    output = format_prompt_display(
        conversation_count=3,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4-mini",
        total_used=5000,
    )

    # Cumulative below $1 → 3 decimals.
    assert "T:$0.005" in output
    # Previous-turn slot below $1 → 4 decimals.
    assert "P:$0.0020" in output


# --- Window-slot collapse ---------------------------------------------------


def test_window_suppressed_when_equals_cumulative(monkeypatch):
    """Until enough turns have accumulated that older buckets fall outside
    the recent window, the window sum equals the cumulative — repeating
    the same number is visual noise. The W: slot is omitted until it
    actually differs from T:."""
    _set_cost_state(monkeypatch, cost=3.0, turn_costs=[1.0, 2.0])

    output = format_prompt_display(
        conversation_count=2,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4",
        total_used=1000,
    )

    paren_section = re.search(r"\(~T:[^)]+\)", output)
    assert paren_section is not None
    body = paren_section.group()
    # T: and P: shown; W: collapsed (would have been $3.00 == T:).
    assert "T:$3.00" in body
    assert "P:$2.00" in body
    assert "W:" not in body


def test_window_shown_when_diverges_from_cumulative(monkeypatch):
    """Once older buckets roll off the recent window — typically after the
    11th turn for the default window of 10 — the window sum is less than
    the cumulative and should appear. This is the moment where the W: slot
    actually carries information."""
    _set_cost_state(monkeypatch, cost=11.0, turn_costs=[1.0] * 11)

    output = format_prompt_display(
        conversation_count=11,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4",
        total_used=1000,
    )

    paren_section = re.search(r"\(~T:[^)]+\)", output)
    assert paren_section is not None
    body = paren_section.group()
    assert "T:$11.00" in body
    assert "W:$10.00" in body
    assert "P:$1.00" in body


# --- Previous-slot collapse -------------------------------------------------


def test_previous_zero_is_omitted(monkeypatch):
    """A $0.00 previous-turn entry is misleading — it could come from an
    unpriced call or a refused call where the user message bucket survived.
    Either way "$0.0000" suggests the turn was free, not unpriced. Omit
    the slot instead."""
    _set_cost_state(monkeypatch, cost=2.50, turn_costs=[1.00, 1.50, 0.0])

    output = format_prompt_display(
        conversation_count=3,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4-mini",
        total_used=1000,
    )

    paren_section = re.search(r"\(~T:[^)]+\)", output)
    assert paren_section is not None
    body = paren_section.group()
    # Only T: shown — W: collapses (equal to T:) AND P: collapses (=0).
    assert body == "(~T:$2.50)"


def test_previous_zero_with_window_diverged_shows_two_values(monkeypatch):
    """Common shape once the session has crossed the window boundary AND
    the most recent call wasn't priced. T: > W: > 0, P: omitted."""
    # 11 buckets: 10 priced + 1 zero (most recent).
    # Cumulative = $10.00, window = sum(buckets[1:11]) = $9 + 0 = $9.00.
    _set_cost_state(monkeypatch, cost=10.00, turn_costs=[1.00] * 10 + [0.0])

    output = format_prompt_display(
        conversation_count=11,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4-mini",
        total_used=1000,
    )

    paren_section = re.search(r"\(~T:[^)]+\)", output)
    assert paren_section is not None
    body = paren_section.group()
    assert "T:$10.00" in body
    assert "W:$9.00" in body
    assert "P:" not in body  # zero last-turn omitted


# --- Total-only (every slot collapses) ---------------------------------------


def test_empty_turn_costs_shows_only_cumulative(monkeypatch):
    """If TURN_COSTS_USD is empty (e.g., cost was reported before any user
    message was appended), don't render bogus zero slots."""
    _set_cost_state(monkeypatch, cost=0.50, turn_costs=[])

    output = format_prompt_display(
        conversation_count=1,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4-mini",
        total_used=100,
    )

    assert "(~T:$0.500)" in output


def test_all_zero_buckets_show_only_cumulative(monkeypatch):
    """If every per-turn bucket is 0 (e.g., a session entirely on a model
    litellm can't price), but cumulative is non-zero for some reason —
    just show T:."""
    _set_cost_state(monkeypatch, cost=0.50, turn_costs=[0.0, 0.0, 0.0])

    output = format_prompt_display(
        conversation_count=3,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4-mini",
        total_used=1000,
    )

    paren_section = re.search(r"\(~T:[^)]+\)", output)
    assert paren_section is not None
    body = paren_section.group()
    assert body == "(~T:$0.500)"  # only T:


# --- Disabled / configurable window -----------------------------------------


def test_no_cost_annotation_when_disabled(monkeypatch):
    _set_cost_state(monkeypatch, cost=10.0, turn_costs=[1.0] * 10, show=False)

    output = format_prompt_display(
        conversation_count=10,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4-mini",
        total_used=1000,
    )

    assert "$10" not in output
    assert "T:$" not in output
    assert "(~" not in output


def test_recent_window_uses_configurable_size(monkeypatch):
    """Sanity check that RECENT_TURN_WINDOW drives the W: sum so it can
    be tuned per-user via config."""
    turn_costs = [1.0] * 20
    monkeypatch.setattr(config, "SHOW_COST_ESTIMATE", True, raising=False)
    monkeypatch.setattr(config, "SESSION_COST_USD", 20.0, raising=False)
    monkeypatch.setattr(config, "TURN_COSTS_USD", turn_costs, raising=False)
    monkeypatch.setattr(config, "RECENT_TURN_WINDOW", 5, raising=False)

    output = format_prompt_display(
        conversation_count=20,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4",
        total_used=1000,
    )

    # Last 5 buckets × $1 each → W:$5.00, P:$1.00, T:$20.00.
    assert "T:$20.00" in output
    assert "W:$5.00" in output
    assert "P:$1.00" in output
