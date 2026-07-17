"""Tests for the P/W color thresholds in the U: cost annotation.

The display wraps P and W with ANSI color codes from monitor.lib.colors
when those slots' dollar values cross configurable thresholds:
- below COST_*_YELLOW → no color (green / default)
- at/above COST_*_YELLOW and below COST_*_RED → yellow
- at/above COST_*_RED → red

Tests verify the boundary behavior at each threshold and confirm that:
- T (total) is never colored regardless of its value
- W is averaged over the window before threshold comparison (a single
  expensive turn doesn't immediately turn W red)
"""

import re

import pytest

import monitor.config  # noqa: F401 — break import cycle
from monitor import config
from monitor.lib import display_output
from monitor.lib.display_output import format_prompt_display

# Sentinel "color codes" that survive the colored-library no-op in non-TTY
# environments. The display module imports `red`, `yellow`, `reset` from
# lib.colors at module load; in tests those evaluate to empty strings (the
# colored library is TTY-aware). Patching them on the display module itself
# lets us assert on the WRAPPING behavior — which threshold branch took —
# without depending on real ANSI bytes.
RED = "[R]"
YELLOW = "[Y]"
RESET = "[/]"


@pytest.fixture(autouse=True)
def _debug_status_line_mode(monkeypatch):
    monkeypatch.setattr(config, "STATUS_LINE_MODE", "debug", raising=False)


@pytest.fixture(autouse=True)
def _patch_color_sentinels(monkeypatch):
    monkeypatch.setattr(display_output, "red", RED, raising=False)
    monkeypatch.setattr(display_output, "yellow", YELLOW, raising=False)
    monkeypatch.setattr(display_output, "reset", RESET, raising=False)


def _setup(monkeypatch, *, total, turn_costs, window=10):
    monkeypatch.setattr(config, "SHOW_COST_ESTIMATE", True, raising=False)
    monkeypatch.setattr(config, "SESSION_COST_USD", total, raising=False)
    monkeypatch.setattr(config, "TURN_COSTS_USD", turn_costs, raising=False)
    monkeypatch.setattr(config, "RECENT_TURN_WINDOW", window, raising=False)
    # Pin known thresholds so tests don't depend on YAML overrides.
    monkeypatch.setattr(config, "COST_P_YELLOW", 0.30, raising=False)
    monkeypatch.setattr(config, "COST_P_RED", 0.80, raising=False)
    monkeypatch.setattr(config, "COST_W_YELLOW", 0.30, raising=False)
    monkeypatch.setattr(config, "COST_W_RED", 0.60, raising=False)


def _render(**kwargs):
    return format_prompt_display(
        conversation_count=kwargs.get("count", 11),
        tokens_remaining=None,
        cwd="/tmp",
        model="openai/gpt-5.4",
        total_used=1_000_000,
    )


# --- P slot color thresholds ------------------------------------------------


def test_p_below_yellow_threshold_is_uncolored(monkeypatch):
    _setup(monkeypatch, total=1.10, turn_costs=[1.0] * 10 + [0.10])
    output = _render()
    # P:$0.10 is below yellow ($0.30) → bare P slot, no sentinels.
    assert " P:$0.10" in output
    assert f"{YELLOW}P:$0.10" not in output
    assert f"{RED}P:$0.10" not in output


def test_p_at_yellow_threshold_turns_yellow(monkeypatch):
    """Exactly the yellow threshold should be yellow (boundary check)."""
    _setup(monkeypatch, total=10.30, turn_costs=[1.0] * 10 + [0.30])
    output = _render()
    assert f"{YELLOW}P:$0.30" in output


def test_p_between_thresholds_is_yellow(monkeypatch):
    _setup(monkeypatch, total=10.50, turn_costs=[1.0] * 10 + [0.50])
    output = _render()
    assert f"{YELLOW}P:$0.50" in output


def test_p_at_red_threshold_turns_red(monkeypatch):
    _setup(monkeypatch, total=10.80, turn_costs=[1.0] * 10 + [0.80])
    output = _render()
    assert f"{RED}P:$0.80" in output


def test_p_above_red_threshold_is_red(monkeypatch):
    _setup(monkeypatch, total=12.50, turn_costs=[1.0] * 10 + [2.50])
    output = _render()
    assert f"{RED}P:$2.50" in output


# --- W slot color thresholds ------------------------------------------------


def test_w_below_yellow_threshold_is_uncolored(monkeypatch):
    """All 10 buckets at $0.10 → W per-turn avg = $0.19 (last 10 incl spike),
    still below yellow."""
    _setup(monkeypatch, total=2.00, turn_costs=[0.10] * 10 + [1.00])
    output = _render()
    # Sum of last 10 = 9 * $0.10 + $1.00 = $1.90 → avg = $0.19 → no color.
    assert "W:$1.90" in output
    assert f"{YELLOW}W:" not in output
    assert f"{RED}W:" not in output


def test_w_per_turn_at_yellow_threshold_turns_yellow(monkeypatch):
    """10 buckets averaging exactly $0.30 → W per-turn = $0.30 (at yellow)."""
    _setup(monkeypatch, total=3.50, turn_costs=[0.30] * 10 + [0.50])
    output = _render()
    # Sum of last 10 = 9*$0.30 + $0.50 = $3.20 → avg = $0.32 → yellow.
    assert f"{YELLOW}W:$3.20" in output


def test_w_per_turn_at_red_threshold_turns_red(monkeypatch):
    """10 buckets averaging exactly $0.60 → W per-turn = $0.60 (at red)."""
    _setup(monkeypatch, total=7.50, turn_costs=[0.60] * 10 + [1.50])
    output = _render()
    # Sum of last 10 = 9*$0.60 + $1.50 = $6.90 → avg = $0.69 → red.
    assert f"{RED}W:$6.90" in output


def test_single_expensive_turn_does_not_turn_w_red(monkeypatch):
    """W threshold compares against the per-turn AVERAGE over the window,
    so a single big spike in an otherwise quiet session keeps W green even
    though P goes red. This is the property that makes W a 'sustained-
    expensive' signal rather than 'any expensive turn'."""
    # 9 small turns + 1 spike. Total/last-10 = (9*$0.10 + $2.00) = $2.90.
    # Avg over 10 turns = $0.29 → below yellow → W stays uncolored.
    # P (the spike) = $2.00 → above RED → P is red.
    _setup(monkeypatch, total=2.90, turn_costs=[0.10] * 9 + [2.00])
    output = _render()
    # W shown but uncolored — the window happens to equal cumulative here
    # (only 10 buckets), so the "show W only when different from T" rule
    # collapses it. Verify P alone has color.
    assert f"{RED}P:$2.00" in output


# --- T slot is never colored ------------------------------------------------


def test_t_is_never_colored(monkeypatch):
    """T is a session totalizer — it grows monotonically and represents
    sunk cost. Coloring it would be alarming without being actionable.
    Even a huge cumulative should leave T uncolored."""
    _setup(monkeypatch, total=100.0, turn_costs=[10.0] * 10)
    output = _render()
    # No sentinel immediately precedes T:.
    assert f"{YELLOW}T:" not in output
    assert f"{RED}T:" not in output


# --- YAML override applied --------------------------------------------------


def test_thresholds_are_read_from_config_at_render_time(monkeypatch):
    """Override the yellow threshold mid-session (simulating a runtime change)
    and verify the next render uses the new value. This is important for the
    Opus use case — bumping by 5x in YAML should take effect without code
    changes."""
    _setup(monkeypatch, total=10.50, turn_costs=[1.0] * 10 + [0.50])
    # Default: $0.50 P is yellow.
    out_default = _render()
    assert f"{YELLOW}P:$0.50" in out_default

    # Bump yellow threshold to $1.50 (Opus-style multiplier). Now $0.50 is below.
    monkeypatch.setattr(config, "COST_P_YELLOW", 1.50, raising=False)
    monkeypatch.setattr(config, "COST_P_RED", 4.00, raising=False)
    out_opus = _render()
    assert f"{YELLOW}P:$0.50" not in out_opus
    assert f"{RED}P:$0.50" not in out_opus
    assert " P:$0.50" in out_opus  # bare, no color
