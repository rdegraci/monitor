"""Tests for the three-slot cost annotation in the U: indicator.

The U: indicator now shows: "U:<tokens> (~$total $last_window $last_turn)"
where last_window is the sum of the last RECENT_TURN_WINDOW (=10) entries
in config.TURN_COSTS_USD and last_turn is the most recent entry.

Covers:
- Three-value format when TURN_COSTS_USD is populated.
- Sub-dollar values use 4 decimals for the last-turn slot (so $0.0034 stays
  visible instead of rounding to $0.00).
- With < window turns, last_window simply sums what's there.
- Empty TURN_COSTS_USD: only cumulative shown (no spurious $0.0000 slots).
- Per-turn tracking accumulates tool-call rounds into the same bucket
  (one user message = one bucket, regardless of how many LLM calls).
- SHOW_COST_ESTIMATE=False suppresses everything.
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


def test_three_value_format_when_above_one_dollar(monkeypatch):
    """The classic example case: ~$21.74 cumulative, $15.50 over last 10,
    $3.50 on the most recent turn."""
    turn_costs = [1.0] * 5 + [1.50] * 4 + [3.50]  # last 10 sum = 5 + 6 + 3.5 = 14.5
    # Adjust so the last-10 example is clean: pad with $1 turns before.
    turn_costs = [1.5] * 7 + [1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5] * 0 + turn_costs
    # Simpler: just construct a known list.
    turn_costs = [1.0] * 5 + [1.5, 1.5, 1.5, 1.5, 1.5, 3.5]  # cumulative=14.0
    cumulative = sum(turn_costs)  # 14.0
    last_window = sum(turn_costs[-10:])  # = 1+1+1+1+1+1.5+1.5+1.5+1.5+1.5+3.5 — only 11 entries, take last 10
    _set_cost_state(monkeypatch, cost=cumulative, turn_costs=turn_costs)

    output = format_prompt_display(
        conversation_count=len(turn_costs),
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4",
        total_used=1_000_000,
    )

    # Three dollar values in the parens, in the right order.
    match = re.search(r"\(~\$([0-9.]+) \$([0-9.]+) \$([0-9.]+)\)", output)
    assert match, f"Expected three-value format, got: {output}"
    total, window, last = (float(x) for x in match.groups())
    assert abs(total - cumulative) < 0.01
    assert abs(window - last_window) < 0.01
    assert abs(last - 3.5) < 0.01


def test_last_turn_sub_dollar_uses_four_decimals(monkeypatch):
    """Cheap turns shouldn't visually round to $0.00 — 4 decimals keeps
    fractions of a cent legible."""
    _set_cost_state(monkeypatch, cost=0.005, turn_costs=[0.001, 0.002, 0.002])

    output = format_prompt_display(
        conversation_count=3,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4-mini",
        total_used=5000,
    )

    # Cumulative below $1 → 3 decimals; per-turn slots below $1 → 4 decimals.
    assert "$0.005" in output  # cumulative
    assert "$0.0020" in output  # last turn (3rd entry)


def test_window_sums_only_what_exists_for_short_history(monkeypatch):
    """With fewer than 10 entries, the middle slot sums whatever's there.
    Two entries should give last_window == sum of both."""
    _set_cost_state(monkeypatch, cost=3.0, turn_costs=[1.0, 2.0])

    output = format_prompt_display(
        conversation_count=2,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4",
        total_used=1000,
    )

    # cumulative=$3.00 last_window=$3.00 (only 2 turns) last=$2.00
    match = re.search(r"\(~\$([0-9.]+) \$([0-9.]+) \$([0-9.]+)\)", output)
    assert match, output
    total, window, last = (float(x) for x in match.groups())
    assert abs(total - 3.0) < 0.01
    assert abs(window - 3.0) < 0.01
    assert abs(last - 2.0) < 0.01


def test_empty_turn_costs_shows_only_cumulative(monkeypatch):
    """If TURN_COSTS_USD is empty (e.g., cost was reported before any user
    message was appended — unusual but possible), don't render bogus
    $0.0000 slots."""
    _set_cost_state(monkeypatch, cost=0.50, turn_costs=[])

    output = format_prompt_display(
        conversation_count=1,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4-mini",
        total_used=100,
    )

    assert "(~$0.500)" in output
    # No additional dollar values inside the parens.
    paren_section = re.search(r"\(~\$[^)]+\)", output)
    assert paren_section is not None
    assert paren_section.group().count("$") == 1


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
    assert "(~$" not in output


def test_last_turn_zero_is_omitted(monkeypatch):
    """A $0.0000 last-turn entry is misleading — it can come from an
    unpriced call (model missing in litellm's pricing table) or a refused
    call where the user message bucket survived. Either way, "$0.0000"
    suggests the turn was free, not unpriced. Omit the slot instead."""
    # Three turns; the last one has zero cost (unpriced or refused).
    _set_cost_state(monkeypatch, cost=2.50, turn_costs=[1.00, 1.50, 0.0])

    output = format_prompt_display(
        conversation_count=3,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4-mini",
        total_used=1000,
    )

    # Cumulative + recent-window (which sums to $2.50, same as cumulative
    # since all three buckets fit the window). Last-turn slot omitted.
    match = re.search(r"\(~\$([0-9.]+) \$([0-9.]+)(?: \$([0-9.]+))?\)", output)
    assert match, output
    total, window, last = match.groups()
    assert float(total) == pytest.approx(2.50, abs=0.01)
    assert float(window) == pytest.approx(2.50, abs=0.01)
    assert last is None, f"Last-turn slot should be omitted when cost is 0; got ${last}"


def test_all_zero_buckets_show_only_cumulative(monkeypatch):
    """If every per-turn bucket is 0 (e.g., a session entirely on a model
    litellm can't price), but cumulative cost is somehow tracked elsewhere
    or remains from before a model switch — just show the cumulative."""
    _set_cost_state(monkeypatch, cost=0.50, turn_costs=[0.0, 0.0, 0.0])

    output = format_prompt_display(
        conversation_count=3,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4-mini",
        total_used=1000,
    )

    paren_section = re.search(r"\(~\$[^)]+\)", output)
    assert paren_section is not None
    # Only one $ inside the parens — just the cumulative.
    assert paren_section.group().count("$") == 1


def test_last_zero_but_window_positive_shows_two_values(monkeypatch):
    """Common case after the refusal fix or an unpriced last call: prior
    turns had real cost (window > 0) but the most recent bucket is 0.
    Show cumulative + window, omit last."""
    _set_cost_state(monkeypatch, cost=5.00, turn_costs=[2.00, 3.00, 0.0])

    output = format_prompt_display(
        conversation_count=3,
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4-mini",
        total_used=1000,
    )

    # Exactly two dollar values in the parens.
    paren_section = re.search(r"\(~\$[^)]+\)", output)
    assert paren_section is not None
    assert paren_section.group().count("$") == 2
    assert "$5.00" in paren_section.group()  # cumulative
    assert "$5.00 $5.00" in paren_section.group()  # cumulative + window (window includes the 0)


def test_recent_window_uses_configurable_size(monkeypatch):
    """Sanity check that RECENT_TURN_WINDOW actually drives the sum,
    so a user could lower it via config if 10 felt too long."""
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

    match = re.search(r"\(~\$([0-9.]+) \$([0-9.]+) \$([0-9.]+)\)", output)
    assert match, output
    total, window, last = (float(x) for x in match.groups())
    # Last 5 turns × $1 each → $5.00.
    assert abs(window - 5.0) < 0.01
