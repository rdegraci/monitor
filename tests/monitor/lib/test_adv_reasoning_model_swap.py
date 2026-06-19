"""Tests for the single-turn ADV_REASONING_MODEL swap.

When a per-turn reasoning override is active (set by the auto-bump heuristic or
tool-failure escalation), call_litellm_completion transiently swaps the model to
the more-capable ADV_REASONING_MODEL for that call only — kwargs only, never
set_model. Calibration data for the swapped round-trip is attributed to the ADV
model so the configured default's rate calibration stays clean.

Covers:
- Swap fires only when an override is active AND a distinct, reasoning-capable
  ADV model is configured.
- The swapped call caps max_completion_tokens at the ADV output window.
- No swap when override inactive / ADV unset / ADV == base / ADV non-reasoning.
- update_token_usage attributes a swap turn's tokens+cost to the ADV model and
  leaves the base model's entry untouched.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from monitor import config
from monitor.lib import llm_utils, model_pricing


def _capture_completion(monkeypatch):
    """Patch litellm.completion to capture the kwargs it is called with."""
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(llm_utils.litellm, "completion", fake_completion)
    return captured


def _reasoning_state(monkeypatch, **overrides):
    defaults = {
        "MODEL": "openai/gpt-5.4-mini",
        "ADV_REASONING_MODEL": "openai/gpt-5.4",
        "ADV_REASONING_MODEL_OUTPUT_WINDOW": None,
        "REASONING_MODEL_PREFIX": "openai/gpt-5",
        "REASONING_EFFORT": "low",
        "REASONING_MAX_COMPLETION_TOKENS": 25000,
        "CURRENT_TURN_REASONING_OVERRIDE": "high",
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        monkeypatch.setattr(config, key, value, raising=False)


def _call(model="openai/gpt-5.4-mini"):
    llm_utils.call_litellm_completion(
        model=model,
        messages=[{"role": "user", "content": "hi"}],
        tool_descriptions=[],
        gemini_tool_descriptions=[],
    )


def test_swap_fires_when_override_active_and_adv_configured(monkeypatch):
    _reasoning_state(monkeypatch)
    captured = _capture_completion(monkeypatch)
    _call()
    assert captured["model"] == "openai/gpt-5.4"
    assert captured["reasoning_effort"] == "high"


def test_swap_caps_max_completion_tokens_at_adv_output_window(monkeypatch):
    _reasoning_state(monkeypatch, ADV_REASONING_MODEL_OUTPUT_WINDOW=10_000)
    captured = _capture_completion(monkeypatch)
    _call()
    assert captured["model"] == "openai/gpt-5.4"
    # min(REASONING_MAX_COMPLETION_TOKENS=25000, adv window=10000)
    assert captured["max_completion_tokens"] == 10_000


def test_no_swap_when_override_inactive(monkeypatch):
    _reasoning_state(monkeypatch, CURRENT_TURN_REASONING_OVERRIDE=None)
    captured = _capture_completion(monkeypatch)
    _call()
    assert captured["model"] == "openai/gpt-5.4-mini"
    assert captured["reasoning_effort"] == "low"


def test_no_swap_when_adv_unset(monkeypatch):
    _reasoning_state(monkeypatch, ADV_REASONING_MODEL=None)
    captured = _capture_completion(monkeypatch)
    _call()
    assert captured["model"] == "openai/gpt-5.4-mini"


def test_no_swap_when_adv_equals_base(monkeypatch):
    _reasoning_state(monkeypatch, ADV_REASONING_MODEL="openai/gpt-5.4-mini")
    captured = _capture_completion(monkeypatch)
    _call()
    assert captured["model"] == "openai/gpt-5.4-mini"


def test_no_swap_when_adv_not_reasoning_capable(monkeypatch):
    # ADV model does not contain REASONING_MODEL_PREFIX → not swapped in.
    _reasoning_state(monkeypatch, ADV_REASONING_MODEL="anthropic/claude-sonnet-4-6")
    captured = _capture_completion(monkeypatch)
    _call()
    assert captured["model"] == "openai/gpt-5.4-mini"


def test_swap_turn_attributed_to_adv_model(monkeypatch):
    """A swapped round-trip's calibration lands on the ADV model; the base
    model's entry is untouched."""
    from monitor.lib import token_management

    monkeypatch.setattr(config, "MODEL", "openai/gpt-5.4-mini", raising=False)
    monkeypatch.setattr(config, "ADV_REASONING_MODEL", "openai/gpt-5.4", raising=False)
    monkeypatch.setattr(config, "REASONING_MODEL_PREFIX", "openai/gpt-5", raising=False)
    monkeypatch.setattr(config, "REASONING_EFFORT", "low", raising=False)
    monkeypatch.setattr(config, "REASONING_EFFORT_RATE_MULTIPLIER",
                        {"low": 0.75, "medium": 1.0, "high": 1.75}, raising=False)
    monkeypatch.setattr(config, "CURRENT_TURN_REASONING_OVERRIDE", "high", raising=False)
    monkeypatch.setattr(config, "SESSION_CALIBRATION_BY_MODEL", {}, raising=False)
    monkeypatch.setattr(config, "SESSION_COST_USD", 0.0, raising=False)
    monkeypatch.setattr(config, "TURN_COSTS_USD", [0.0], raising=False)

    fake_litellm = SimpleNamespace(completion_cost=lambda **_: 0.05)
    import sys
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=200, completion_tokens=100, total_tokens=300)
    )
    token_management.update_token_usage(response)

    adv = model_pricing.calibration_entry("openai/gpt-5.4")
    base = model_pricing.calibration_entry("openai/gpt-5.4-mini")
    assert adv["total_tokens"] == 300
    assert adv["cost_usd"] == pytest.approx(0.05)
    # 300 tokens weighted by the high (override) multiplier 1.75.
    assert adv["effort_weighted_tokens"] == pytest.approx(300 * 1.75)
    # Base model untouched by the swap turn.
    assert base["total_tokens"] == 0
    assert base["cost_usd"] == 0.0


def test_explicit_model_arg_overrides_derived_attribution(monkeypatch):
    """A caller that ran a non-default model (no override active, so the
    derivation would wrongly pick config.MODEL) can pass model= to attribute
    its spend correctly — the plumbing that future commit/sub-agent paths use."""
    from monitor.lib import token_management

    monkeypatch.setattr(config, "MODEL", "openai/gpt-5.4-mini", raising=False)
    monkeypatch.setattr(config, "ADV_REASONING_MODEL", None, raising=False)
    monkeypatch.setattr(config, "CURRENT_TURN_REASONING_OVERRIDE", None, raising=False)
    monkeypatch.setattr(config, "SESSION_CALIBRATION_BY_MODEL", {}, raising=False)
    monkeypatch.setattr(config, "SESSION_COST_USD", 0.0, raising=False)
    monkeypatch.setattr(config, "TURN_COSTS_USD", [0.0], raising=False)

    fake_litellm = SimpleNamespace(completion_cost=lambda **_: 0.04)
    import sys
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=40_000, completion_tokens=10_000, total_tokens=50_000)
    )
    # Ran on a different model than config.MODEL (e.g. COMMIT_MODEL).
    token_management.update_token_usage(response, model="openai/gpt-5.4")

    commit_model = model_pricing.calibration_entry("openai/gpt-5.4")
    base = model_pricing.calibration_entry("openai/gpt-5.4-mini")
    assert commit_model["total_tokens"] == 50_000
    assert commit_model["cost_usd"] == pytest.approx(0.04)
    # config.MODEL's entry is NOT polluted by the other model's spend.
    assert base["total_tokens"] == 0
    assert base["cost_usd"] == 0.0
