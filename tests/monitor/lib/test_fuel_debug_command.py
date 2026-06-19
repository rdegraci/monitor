"""Tests for the :fuel_debug built-in command."""

import monitor.config  # noqa: F401
from monitor import config
from monitor.lib.built_in_commands import fuel_debug_command


def _set_state(monkeypatch, **overrides):
    """Apply runtime config values needed by fuel_debug tests.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        **overrides: Config values to override.
    """
    defaults = {
        "MODEL": "openai/gpt-5.4-mini",
        "REASONING_EFFORT": "medium",
        "REASONING_MODEL_PREFIX": "openai/gpt-5",
        "MODEL_TOKEN_RATE_PER_MTOK": {
            "openai/gpt-5.4": 1.0,
            "openai/gpt-5.4-mini": 0.5,
        },
        "TOKEN_RATE_ANCHOR_MODEL": "openai/gpt-5.4",
        "DEFAULT_TOKEN_RATE_PER_MTOK": 1.0,
        "DAILY_COST_TARGET_USD": 5.0,
        "SESSION_COST_USD": 0.0,
        "SESSION_TOTAL_TOKENS": 0,
        "SESSION_CACHED_INPUT_TOKENS": 0,
        "SESSION_UNCACHED_INPUT_TOKENS": 0,
        "SESSION_OUTPUT_TOKENS": 0,
        "SESSION_EFFORT_WEIGHTED_TOKENS": 0.0,
        "SESSION_EFFORT_WEIGHT_TOKENS": 0,
        "SESSION_TOKEN_BUDGET": None,
        "REASONING_EFFORT_RATE_MULTIPLIER": {
            "minimal": 0.5,
            "low": 0.75,
            "medium": 1.0,
            "high": 1.75,
            "xhigh": 2.25,
        },
        "MODEL_PRICING_OVERRIDES": {},
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        monkeypatch.setattr(config, key, value, raising=False)



def test_fuel_debug_uses_observed_ut_rate_when_available(capsys, monkeypatch):
    """Observed T:/U: data should drive the primary suggestion when ample."""
    _set_state(
        monkeypatch,
        SESSION_COST_USD=1.2,
        SESSION_TOTAL_TOKENS=2_000_000,
    )

    fuel_debug_command()
    out = capsys.readouterr().out

    assert "=== Fuel debug ===" in out
    assert "Observed rate / 1M:      0.600000 (medium confidence)" in out
    assert (
        "Basis: observed U:/T: normalized by current multiplier (medium confidence)"
        in out
    )
    assert "Suggested config value:  0.6000000000000001" not in out
    assert "Suggested config value:  0.6" in out
    assert "YAML: openai/gpt-5.4-mini: 0.6" in out



def test_fuel_debug_falls_back_to_theoretical_rate(capsys, monkeypatch):
    """Without meaningful T:/U: data, the command should use the /1M blend."""
    _set_state(monkeypatch)

    fuel_debug_command()
    out = capsys.readouterr().out

    assert "Observed rate / 1M:      unavailable" in out
    assert "Theoretical blend:       0.355" in out
    assert "Empirical blend weights: unavailable" in out
    assert "Basis: theoretical blended rate" in out
    assert "Suggested raw rate / 1M: 0.355000" in out
    assert "Suggested config value:  0.35" in out
    assert "YAML: openai/gpt-5.4-mini: 0.35" in out


def test_fuel_debug_uses_empirical_blend_when_session_mix_is_sufficient(capsys, monkeypatch):
    """Empirical session mix should drive fallback suggestions once ample."""
    _set_state(
        monkeypatch,
        SESSION_CACHED_INPUT_TOKENS=1_600_000,
        SESSION_UNCACHED_INPUT_TOKENS=300_000,
        SESSION_OUTPUT_TOKENS=100_000,
    )

    fuel_debug_command()
    out = capsys.readouterr().out

    assert "Observed rate / 1M:      unavailable" in out
    assert "Empirical confidence:    medium" in out
    assert "Empirical blend weights: cached=0.8000 input=0.1500 output=0.0500" in out
    assert "Empirical blend / 1M:    0.1575" in out
    assert "Basis: empirical blended rate (medium confidence)" in out
    assert "Suggested raw rate / 1M: 0.157500" in out
    assert "Suggested config value:  0.15" in out
    assert "YAML: openai/gpt-5.4-mini: 0.15" in out



def test_fuel_debug_normalizes_observed_by_session_average_multiplier(capsys, monkeypatch):
    """The observed rate is normalized by the session-average multiplier (which
    folds in single-turn upgrades), not the instantaneous steady multiplier, so
    occasional upgrades don't bias the suggested baseline rate high."""
    _set_state(
        monkeypatch,
        REASONING_EFFORT="low",                     # steady multiplier 0.75
        SESSION_COST_USD=1.9,
        SESSION_TOTAL_TOKENS=2_000_000,             # observed = 0.95 / 1M
        SESSION_EFFORT_WEIGHTED_TOKENS=1_900_000.0,
        SESSION_EFFORT_WEIGHT_TOKENS=2_000_000,     # session-average = 0.95
    )

    fuel_debug_command()
    out = capsys.readouterr().out

    assert "Effort multiplier (now):     0.75" in out
    assert "Effort multiplier (session): 0.9500" in out
    assert "Upgrade load:            +26.7% over steady effort" in out
    assert "Observed rate / 1M:      0.950000 (medium confidence)" in out
    # 0.95 / 0.95 = 1.0 baseline — NOT 0.95 / 0.75 = 1.27 (the biased value
    # the old instantaneous-multiplier divide would have produced).
    assert (
        "Basis: observed U:/T: normalized by session-average multiplier (medium confidence)"
        in out
    )
    assert "Suggested config value:  1.0" in out


def test_fuel_debug_help_prints_field_guide(capsys, monkeypatch):
    """':fuel_debug help' prints the field guide, not the live readout."""
    _set_state(monkeypatch)

    fuel_debug_command("help")
    out = capsys.readouterr().out

    assert "WHAT THIS COMMAND IS FOR" in out
    assert "HOW TO CALIBRATE" in out
    assert "=== Fuel debug ===" not in out


def test_fuel_debug_registered_in_built_ins():
    """Verify the built-in command registry exposes :fuel_debug."""
    from monitor.core.built_ins import configure_built_ins
    from monitor.lib.built_ins_utils import is_built_in_function

    configure_built_ins()

    assert is_built_in_function(":fuel_debug") is not None
    assert is_built_in_function("/fuel_debug") is not None
    assert is_built_in_function("fuel_debug") is None
