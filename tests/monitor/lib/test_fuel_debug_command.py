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



def test_fuel_debug_registered_in_built_ins():
    """Verify the built-in command registry exposes :fuel_debug."""
    from monitor.core.built_ins import configure_built_ins
    from monitor.lib.built_ins_utils import is_built_in_function

    configure_built_ins()

    assert is_built_in_function(":fuel_debug") is not None
    assert is_built_in_function("/fuel_debug") is not None
    assert is_built_in_function("fuel_debug") is None
