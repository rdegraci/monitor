"""Tests for the C: indicator color thresholds.

The C: indicator (context remaining as a percentage of the input window)
gets wrapped with ANSI codes based on how close the prompt is to the
configured compaction threshold:

  - blue / default: remaining_percent above the yellow threshold (healthy)
  - yellow: remaining_percent below the yellow threshold (compaction zone)
  - red: remaining_percent below the red threshold, or remaining == 0

Yellow threshold = (1 - AUTO_COMPACT_THRESHOLD_RATIO) × 100.
Red threshold    = yellow_threshold / 2.

Tying thresholds to the compaction ratio means the warning auto-tunes to
the user's policy: tighter compaction (e.g., 0.15) gives earlier color
warnings; lax compaction (e.g., 0.50) means colors only fire when context
is genuinely low.
"""

import pytest

import monitor.config  # noqa: F401 — break import cycle
from monitor import config
from monitor.lib import display_output
from monitor.lib.display_output import format_prompt_display

# Sentinel "color codes" — the colored library returns empty strings in
# non-TTY environments, so we patch the symbols on the display module to
# survive in tests. (Same pattern as test_cost_color_thresholds.py.)
BLUE = "[B]"
YELLOW = "[Y]"
RED = "[R]"
RESET = "[/]"


@pytest.fixture(autouse=True)
def _patch_color_sentinels(monkeypatch):
    monkeypatch.setattr(display_output, "blue", BLUE, raising=False)
    monkeypatch.setattr(display_output, "yellow", YELLOW, raising=False)
    monkeypatch.setattr(display_output, "red", RED, raising=False)
    monkeypatch.setattr(display_output, "reset", RESET, raising=False)


def _render(*, remaining, budget, model="openai/gpt-5.4"):
    """Render with a known context_remaining + context_budget so we can
    verify the resulting color around specific percentages."""
    return format_prompt_display(
        conversation_count=10,
        tokens_remaining=None,
        cwd="/tmp",
        model=model,
        context_remaining=remaining,
        context_budget=budget,
    )


# --- Default ratio 0.30 (yellow < 70%, red < 35%) ---------------------------


def test_blue_when_well_above_yellow_threshold(monkeypatch):
    monkeypatch.setattr(config, "AUTO_COMPACT_THRESHOLD_RATIO", 0.30, raising=False)
    # 95% remaining → comfortably above the 70% yellow threshold.
    out = _render(remaining=950_000, budget=1_000_000)
    assert f"{BLUE}950000" in out
    assert f"{YELLOW}950000" not in out
    assert f"{RED}950000" not in out


def test_yellow_just_below_yellow_threshold(monkeypatch):
    monkeypatch.setattr(config, "AUTO_COMPACT_THRESHOLD_RATIO", 0.30, raising=False)
    # 65% remaining → below 70% yellow threshold, above 35% red threshold.
    out = _render(remaining=650_000, budget=1_000_000)
    assert f"{YELLOW}650000" in out


def test_yellow_exact_boundary_is_blue(monkeypatch):
    """At exactly the yellow threshold (70%) we want blue — the check is
    strictly < threshold. Equal-to should NOT trip yellow because compaction
    fires AT that threshold; the user is on the boundary, not past it."""
    monkeypatch.setattr(config, "AUTO_COMPACT_THRESHOLD_RATIO", 0.30, raising=False)
    # 70% remaining exactly.
    out = _render(remaining=700_000, budget=1_000_000)
    assert f"{BLUE}700000" in out


def test_red_just_below_red_threshold(monkeypatch):
    monkeypatch.setattr(config, "AUTO_COMPACT_THRESHOLD_RATIO", 0.30, raising=False)
    # 30% remaining → below 35% red threshold.
    out = _render(remaining=300_000, budget=1_000_000)
    assert f"{RED}300000" in out


def test_red_when_remaining_is_zero(monkeypatch):
    """Literal zero remaining ALWAYS renders red regardless of percentage
    math — the model is out of room and the next request will fail."""
    monkeypatch.setattr(config, "AUTO_COMPACT_THRESHOLD_RATIO", 0.99, raising=False)
    out = _render(remaining=0, budget=1_000_000)
    assert f"{RED}0" in out


# --- Lax ratio 0.50 (yellow < 50%, red < 25%) -------------------------------


def test_lax_ratio_keeps_blue_in_middle_range(monkeypatch):
    """With ratio=0.50 (compaction fires at 50% used), the user's session
    typically sits at C >= 50% and stays blue throughout. Color only fires
    when the session genuinely approaches the compaction trigger."""
    monkeypatch.setattr(config, "AUTO_COMPACT_THRESHOLD_RATIO", 0.50, raising=False)
    # 55% remaining → above the 50% yellow threshold for lax compaction.
    out = _render(remaining=550_000, budget=1_000_000)
    assert f"{BLUE}550000" in out


def test_lax_ratio_yellow_at_low_remaining(monkeypatch):
    monkeypatch.setattr(config, "AUTO_COMPACT_THRESHOLD_RATIO", 0.50, raising=False)
    # 40% remaining → below 50% yellow threshold, above 25% red.
    out = _render(remaining=400_000, budget=1_000_000)
    assert f"{YELLOW}400000" in out


# --- Tight ratio 0.15 (yellow < 85%, red < 42.5%) ---------------------------


def test_tight_ratio_yellow_fires_earlier(monkeypatch):
    """With ratio=0.15 (compaction fires at 15% used = 85% remaining),
    yellow fires whenever C drops below 85%. The same C: 80% that would
    stay blue under default compaction now correctly warns."""
    monkeypatch.setattr(config, "AUTO_COMPACT_THRESHOLD_RATIO", 0.15, raising=False)
    out = _render(remaining=800_000, budget=1_000_000)
    assert f"{YELLOW}800000" in out


def test_tight_ratio_red_threshold_scales(monkeypatch):
    """Red threshold under ratio=0.15 = 85% / 2 = 42.5%."""
    monkeypatch.setattr(config, "AUTO_COMPACT_THRESHOLD_RATIO", 0.15, raising=False)
    out = _render(remaining=400_000, budget=1_000_000)
    assert f"{RED}400000" in out


# --- Edge cases -------------------------------------------------------------


def test_invalid_ratio_falls_back_to_default(monkeypatch):
    """If AUTO_COMPACT_THRESHOLD_RATIO is somehow missing or invalid (e.g.,
    a bad YAML value that the loader logged a warning about but didn't
    overwrite), the helper falls through to historical blue rather than
    crashing the prompt display."""
    monkeypatch.setattr(config, "AUTO_COMPACT_THRESHOLD_RATIO", None, raising=False)
    # Should fall back to the default 0.30 → yellow at 70%, red at 35%.
    out = _render(remaining=600_000, budget=1_000_000)
    # 60% remaining → below default yellow threshold (70%) → yellow.
    assert f"{YELLOW}600000" in out
