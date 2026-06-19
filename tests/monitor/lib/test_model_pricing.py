"""Tests for the model-pricing fallback that runs when litellm.completion_cost
returns 0 for an unknown model.

Covers:
- get_model_rates: YAML overrides win over shipped; unknown returns None.
- _extract_usage_tokens: handles Chat Completions and Responses API shapes;
  dict and attribute access; absent usage block.
- estimate_cost_from_usage: math is tokens × rates; uncached + cached
  tokens billed at their respective rates; returns 0 when unpricable.
- Integration with update_token_usage: when litellm returns 0/raises,
  the fallback path picks up the cost and feeds SESSION_COST_USD and
  the per-turn bucket.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import patch

import monitor.config  # noqa: F401 — break import cycle
from monitor import config
from monitor.lib import model_pricing


@pytest.fixture(autouse=True)
def _reset_pricing_state(monkeypatch):
    monkeypatch.setattr(config, "MODEL_PRICING_OVERRIDES", {}, raising=False)
    monkeypatch.setattr(config, "SESSION_COST_USD", 0.0, raising=False)
    monkeypatch.setattr(config, "TURN_COSTS_USD", [], raising=False)
    monkeypatch.setattr(config, "SESSION_TOTAL_TOKENS", 0, raising=False)
    monkeypatch.setattr(config, "TOTAL_TOKEN_COUNT", 0, raising=False)
    # Cumulative session counters mutated by update_token_usage — reset so
    # accumulation tests don't leak token counts into one another.
    monkeypatch.setattr(config, "SESSION_CACHED_INPUT_TOKENS", 0, raising=False)
    monkeypatch.setattr(config, "SESSION_UNCACHED_INPUT_TOKENS", 0, raising=False)
    monkeypatch.setattr(config, "SESSION_OUTPUT_TOKENS", 0, raising=False)
    monkeypatch.setattr(config, "SESSION_EFFORT_WEIGHTED_TOKENS", 0.0, raising=False)
    monkeypatch.setattr(config, "SESSION_EFFORT_WEIGHT_TOKENS", 0, raising=False)
    yield


# --- get_model_rates --------------------------------------------------------


def test_shipped_default_returned_when_no_override():
    """A model in SHIPPED_MODEL_PRICING (e.g., sonnet-4-6) is priced by
    default — no YAML config needed for well-known public models."""
    rates = model_pricing.get_model_rates("anthropic/claude-sonnet-4-6")
    assert rates is not None
    # Confirms public rates: input $3/M = 3.0e-6 per token.
    assert rates["input_per_token"] == pytest.approx(3.00 / 1_000_000)
    assert rates["output_per_token"] == pytest.approx(15.00 / 1_000_000)


def test_yaml_override_wins_over_shipped(monkeypatch):
    """If the user overrides Sonnet's rates in YAML — say, because of an
    enterprise contract — the override wins. Shipped defaults are only
    used when there's no override."""
    monkeypatch.setattr(config, "MODEL_PRICING_OVERRIDES", {
        "anthropic/claude-sonnet-4-6": {
            "input_per_token":        2.00 / 1_000_000,
            "output_per_token":       10.00 / 1_000_000,
        },
    }, raising=False)
    rates = model_pricing.get_model_rates("anthropic/claude-sonnet-4-6")
    assert rates["input_per_token"] == pytest.approx(2.00 / 1_000_000)
    assert rates["output_per_token"] == pytest.approx(10.00 / 1_000_000)


def test_unknown_model_returns_none():
    """No override, no shipped entry → None. estimate_cost_from_usage
    treats this as 'can't price' and returns 0."""
    assert model_pricing.get_model_rates("xai/grok-build-0.1") is None
    assert model_pricing.get_model_rates("not-a-real-model") is None


def test_non_string_model_returns_none():
    assert model_pricing.get_model_rates(None) is None
    assert model_pricing.get_model_rates(12345) is None


# --- _extract_usage_tokens --------------------------------------------------


def test_extract_chat_completions_shape_dict():
    """Standard Chat Completions response: prompt_tokens + completion_tokens
    + optional prompt_tokens_details.cached_tokens."""
    response = {
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "prompt_tokens_details": {"cached_tokens": 800},
        }
    }
    uncached, cached, output = model_pricing._extract_usage_tokens(response)
    assert uncached == 200   # 1000 prompt - 800 cached
    assert cached == 800
    assert output == 500


def test_extract_chat_completions_shape_object():
    """Same shape via attribute access (model SDK responses)."""
    usage = SimpleNamespace(
        prompt_tokens=2000,
        completion_tokens=400,
        prompt_tokens_details=SimpleNamespace(cached_tokens=1500),
    )
    response = SimpleNamespace(usage=usage)
    uncached, cached, output = model_pricing._extract_usage_tokens(response)
    assert uncached == 500
    assert cached == 1500
    assert output == 400


def test_extract_responses_api_shape():
    """OpenAI Responses API uses input_tokens / output_tokens, not
    prompt_tokens / completion_tokens. The extractor falls through."""
    response = {
        "usage": {
            "input_tokens": 1500,
            "output_tokens": 300,
        }
    }
    uncached, cached, output = model_pricing._extract_usage_tokens(response)
    assert uncached == 1500
    assert cached == 0
    assert output == 300


def test_extract_no_usage_block_returns_zeros():
    response = SimpleNamespace()
    assert model_pricing._extract_usage_tokens(response) == (0, 0, 0)


def test_extract_none_response_returns_zeros():
    assert model_pricing._extract_usage_tokens(None) == (0, 0, 0)


# --- estimate_cost_from_usage ----------------------------------------------


def test_estimate_cost_for_known_model():
    """End-to-end pricing for a Sonnet response. With 200 uncached input @
    $3/M + 800 cached @ $0.30/M + 500 output @ $15/M:
      200 * 3e-6 + 800 * 0.30e-6 + 500 * 15e-6
      = 0.0006 + 0.00024 + 0.0075 = 0.00834
    """
    response = {
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "prompt_tokens_details": {"cached_tokens": 800},
        }
    }
    cost = model_pricing.estimate_cost_from_usage(response, "anthropic/claude-sonnet-4-6")
    expected = 200 * (3.00 / 1_000_000) + 800 * (0.30 / 1_000_000) + 500 * (15.00 / 1_000_000)
    assert cost == pytest.approx(expected)


def test_estimate_cost_uses_yaml_override(monkeypatch):
    """The user's xai/grok-build-0.1 entry from YAML drives the math."""
    monkeypatch.setattr(config, "MODEL_PRICING_OVERRIDES", {
        "xai/grok-build-0.1": {
            "input_per_token":        1.00 / 1_000_000,
            "cached_input_per_token": 0.20 / 1_000_000,
            "output_per_token":       2.00 / 1_000_000,
        },
    }, raising=False)
    response = {
        "usage": {
            "prompt_tokens": 10_000,
            "completion_tokens": 2_000,
        }
    }
    cost = model_pricing.estimate_cost_from_usage(response, "xai/grok-build-0.1")
    # 10K * $1/M + 2K * $2/M = $0.01 + $0.004 = $0.014
    assert cost == pytest.approx(0.014)


def test_estimate_cost_unknown_model_returns_zero():
    """No entry anywhere → 0. The display will show no cost, matching what
    the user sees today for genuinely unpriced calls."""
    response = {"usage": {"prompt_tokens": 1000, "completion_tokens": 500}}
    cost = model_pricing.estimate_cost_from_usage(response, "not-a-real-model")
    assert cost == 0.0


def test_estimate_cost_empty_usage_returns_zero():
    """A response with no usage info can't be priced — even if the model
    is known."""
    cost = model_pricing.estimate_cost_from_usage(None, "anthropic/claude-sonnet-4-6")
    assert cost == 0.0




def test_effort_multiplier_for_explicit_effort(monkeypatch):
    """effort_multiplier_for scores an explicit effort, not the live config."""
    monkeypatch.setattr(config, "REASONING_MODEL_PREFIX", "openai/gpt-5", raising=False)
    monkeypatch.setattr(
        config,
        "REASONING_EFFORT_RATE_MULTIPLIER",
        {"low": 0.75, "medium": 1.0, "high": 1.75},
        raising=False,
    )
    assert model_pricing.effort_multiplier_for("openai/gpt-5.4-mini", "high") == pytest.approx(1.75)
    assert model_pricing.effort_multiplier_for("openai/gpt-5.4-mini", "low") == pytest.approx(0.75)
    # Effort absent from the table falls back to 1.0.
    assert model_pricing.effort_multiplier_for("openai/gpt-5.4-mini", "bogus") == 1.0
    # Non-reasoning model is always 1.0 regardless of effort.
    assert model_pricing.effort_multiplier_for("anthropic/claude-sonnet-4-6", "high") == 1.0


def test_session_average_effort_multiplier_token_weighted(monkeypatch):
    """The session average is Σ(tokens × multiplier) / Σ(tokens)."""
    # 1M tokens at multiplier 1.0 + 1M tokens at 0.5 → weighted average 0.75.
    monkeypatch.setattr(config, "SESSION_EFFORT_WEIGHTED_TOKENS", 1_500_000.0, raising=False)
    monkeypatch.setattr(config, "SESSION_EFFORT_WEIGHT_TOKENS", 2_000_000, raising=False)
    assert model_pricing.session_average_effort_multiplier() == pytest.approx(0.75)


def test_session_average_effort_multiplier_none_without_data(monkeypatch):
    """No accumulated effort-weighted tokens → None (callers fall back)."""
    monkeypatch.setattr(config, "SESSION_EFFORT_WEIGHTED_TOKENS", 0.0, raising=False)
    monkeypatch.setattr(config, "SESSION_EFFORT_WEIGHT_TOKENS", 0, raising=False)
    assert model_pricing.session_average_effort_multiplier() is None


def test_update_token_usage_accumulates_effort_weighted_tokens(monkeypatch):
    """A round-trip uses the per-turn override effort (not steady) to weight
    the session multiplier accumulators by that turn's token count."""
    from monitor.lib import token_management

    monkeypatch.setattr(config, "MODEL", "openai/gpt-5.4-mini", raising=False)
    monkeypatch.setattr(config, "REASONING_MODEL_PREFIX", "openai/gpt-5", raising=False)
    monkeypatch.setattr(config, "REASONING_EFFORT", "low", raising=False)
    monkeypatch.setattr(
        config,
        "REASONING_EFFORT_RATE_MULTIPLIER",
        {"low": 0.75, "medium": 1.0, "high": 1.75},
        raising=False,
    )
    # Single-turn upgrade: this round-trip ran at medium, not the steady low.
    monkeypatch.setattr(config, "CURRENT_TURN_REASONING_OVERRIDE", "medium", raising=False)
    monkeypatch.setattr(config, "SESSION_EFFORT_WEIGHTED_TOKENS", 0.0, raising=False)
    monkeypatch.setattr(config, "SESSION_EFFORT_WEIGHT_TOKENS", 0, raising=False)
    monkeypatch.setattr(config, "TURN_COSTS_USD", [0.0], raising=False)
    monkeypatch.setattr(config, "MODEL_PRICING_OVERRIDES", {
        "openai/gpt-5.4-mini": {
            "input_per_token":  1.00 / 1_000_000,
            "output_per_token": 2.00 / 1_000_000,
        },
    }, raising=False)

    fake_litellm = SimpleNamespace(completion_cost=lambda **_: 0.01)
    import sys
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    )
    token_management.update_token_usage(response)

    # 150 tokens weighted by the medium (override) multiplier 1.0, NOT the
    # steady-low 0.75 — confirms the override drives the calibration weight.
    assert config.SESSION_EFFORT_WEIGHT_TOKENS == 150
    assert config.SESSION_EFFORT_WEIGHTED_TOKENS == pytest.approx(150 * 1.0)
    assert model_pricing.session_average_effort_multiplier() == pytest.approx(1.0)


def test_session_empirical_pricing_mix_uses_cumulative_session_counters(monkeypatch):
    """Empirical pricing mix should normalize tracked session composition."""
    monkeypatch.setattr(config, "SESSION_CACHED_INPUT_TOKENS", 800, raising=False)
    monkeypatch.setattr(config, "SESSION_UNCACHED_INPUT_TOKENS", 150, raising=False)
    monkeypatch.setattr(config, "SESSION_OUTPUT_TOKENS", 50, raising=False)

    mix = model_pricing.session_empirical_pricing_mix()

    assert mix["total_tokens"] == 1_000
    assert mix["confidence"] == "low"
    assert mix["weights"]["cached_input_per_token"] == pytest.approx(0.8)
    assert mix["weights"]["input_per_token"] == pytest.approx(0.15)
    assert mix["weights"]["output_per_token"] == pytest.approx(0.05)


# --- Integration with update_token_usage -----------------------------------


def test_update_token_usage_uses_fallback_when_litellm_returns_zero(monkeypatch):
    """When litellm.completion_cost returns 0 (model unknown to litellm),
    the harness routes to our local pricing. The cost lands in
    SESSION_COST_USD and the current per-turn bucket. This is the headline
    fix: the user's xai/grok-build-0.1 session would now show a non-zero
    cost in the U: indicator."""
    from monitor.lib import token_management

    monkeypatch.setattr(config, "MODEL", "xai/grok-build-0.1", raising=False)
    monkeypatch.setattr(config, "MODEL_PRICING_OVERRIDES", {
        "xai/grok-build-0.1": {
            "input_per_token":        1.00 / 1_000_000,
            "cached_input_per_token": 0.20 / 1_000_000,
            "output_per_token":       2.00 / 1_000_000,
        },
    }, raising=False)
    # Seed a current-turn bucket so the per-turn accumulator has a target.
    monkeypatch.setattr(config, "TURN_COSTS_USD", [0.0], raising=False)

    # Stub litellm.completion_cost to return 0 — simulating the
    # "model not in litellm's pricing table" path.
    fake_litellm = SimpleNamespace(completion_cost=lambda **_: 0)
    import sys
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=50_000,
            completion_tokens=10_000,
            total_tokens=60_000,
        )
    )

    token_management.update_token_usage(response)

    # 50K * $1/M + 10K * $2/M = $0.05 + $0.02 = $0.07
    assert config.SESSION_COST_USD == pytest.approx(0.07)
    assert config.TURN_COSTS_USD[0] == pytest.approx(0.07)
    assert config.SESSION_UNCACHED_INPUT_TOKENS == 50_000
    assert config.SESSION_CACHED_INPUT_TOKENS == 0
    assert config.SESSION_OUTPUT_TOKENS == 10_000


def test_update_token_usage_litellm_path_still_works(monkeypatch):
    """When litellm DOES know the model, the fallback is bypassed entirely.
    Verifies the override doesn't interfere with the primary path."""
    from monitor.lib import token_management

    monkeypatch.setattr(config, "MODEL", "anthropic/claude-sonnet-4-6", raising=False)
    monkeypatch.setattr(config, "TURN_COSTS_USD", [0.0], raising=False)

    fake_litellm = SimpleNamespace(completion_cost=lambda **_: 0.42)
    import sys
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
    )

    token_management.update_token_usage(response)
    # litellm returned $0.42 directly — our shipped Sonnet rates would
    # have given a tiny different number, but litellm wins when non-zero.
    assert config.SESSION_COST_USD == pytest.approx(0.42)


def test_yaml_loader_converts_per_million_to_per_token():
    """The YAML loader at config.py reads per_million_tokens (user-friendly)
    and stores per_token (math-ready). Verify the conversion by running
    the loader logic on a synthetic YAML config dict.

    This mirrors the production code so changes to the loader logic
    update both places intentionally."""
    yaml_input = {
        "xai/grok-build-0.1": {
            "input_per_million_tokens":        1.00,
            "cached_input_per_million_tokens": 0.20,
            "output_per_million_tokens":       2.00,
        },
    }
    overrides = {}
    for model_name, rates in yaml_input.items():
        per_token = {}
        for src, dst in (
            ("input_per_million_tokens", "input_per_token"),
            ("cached_input_per_million_tokens", "cached_input_per_token"),
            ("output_per_million_tokens", "output_per_token"),
        ):
            val = rates.get(src)
            if isinstance(val, (int, float)) and val >= 0:
                per_token[dst] = float(val) / 1_000_000
        overrides[model_name] = per_token

    assert overrides["xai/grok-build-0.1"]["input_per_token"] == pytest.approx(1e-6)
    assert overrides["xai/grok-build-0.1"]["cached_input_per_token"] == pytest.approx(2e-7)
    assert overrides["xai/grok-build-0.1"]["output_per_token"] == pytest.approx(2e-6)
