"""Per-model cost fallback for `update_token_usage`.

litellm provides a built-in pricing table that covers most public-rate
models, and `litellm.completion_cost(response)` is the primary cost
source. But the table doesn't cover every model — brand-new releases,
private deployments, and custom names like ``xai/grok-build-0.1`` all
return 0 from `completion_cost`, leaving the U:'s ``(~T:$N)`` annotation
empty.

This module fills that gap with a two-layer override-first table:

  1. ``config.MODEL_PRICING_OVERRIDES`` — loaded from the YAML
     ``model_pricing:`` block. User-extensible; the right place for
     custom or private models.
  2. ``SHIPPED_MODEL_PRICING`` — the dict in this file. A small list of
     public-rate defaults; mostly a safety net in case litellm's table
     lags behind a model release.

Rates are stored internally as USD per token. YAML accepts the more
natural per-million-tokens form (e.g., ``2.50``) and the loader divides
by 1_000_000 at startup.

When called from `update_token_usage`:
  cost = litellm.completion_cost(response)
  if cost in (0, None) or raised:
      cost = estimate_cost_from_usage(response, config.MODEL)

Same downstream path either way — accumulates into ``SESSION_COST_USD``
and the per-turn bucket. The user sees one cost number; the fallback is
transparent.
"""

import logging

logger = logging.getLogger(__name__)


# USD per token (divide per-M dollar values by 1_000_000). Update when new
# public models ship; YAML overrides take precedence for any matching key.
SHIPPED_MODEL_PRICING = {
    # Anthropic — verified pricing the user shared in this session.
    "anthropic/claude-sonnet-4-6": {
        "input_per_token":        3.00 / 1_000_000,
        "cached_input_per_token": 0.30 / 1_000_000,
        "output_per_token":       15.00 / 1_000_000,
    },
    "anthropic/claude-opus-4-7": {
        "input_per_token":        5.00 / 1_000_000,
        "cached_input_per_token": 0.50 / 1_000_000,
        "output_per_token":       25.00 / 1_000_000,
    },

    # OpenAI gpt-5.4 family. Short-context tier rates (gpt-5.4 has a long-
    # context tier above ~128K that costs ~2x input, ~1.5x output; the
    # fallback approximates by ignoring tier crossover — most sessions
    # stay under it, and an under-estimate is preferable to silent zero).
    "openai/gpt-5.4": {
        "input_per_token":        2.50 / 1_000_000,
        "cached_input_per_token": 0.25 / 1_000_000,
        "output_per_token":       15.00 / 1_000_000,
    },
    "openai/gpt-5.4-mini": {
        # Approximate; mini is roughly 1/10 the price of base.
        "input_per_token":        0.25 / 1_000_000,
        "cached_input_per_token": 0.025 / 1_000_000,
        "output_per_token":       2.00 / 1_000_000,
    },
}


def get_model_rates(model_name):
    """Return the per-token rate dict for ``model_name``, or None when no
    entry exists. YAML overrides take precedence over shipped defaults.

    Args:
        model_name: The full model string (e.g., "anthropic/claude-sonnet-4-6").

    Returns:
        dict | None: Keys are ``input_per_token``, ``cached_input_per_token``,
        ``output_per_token``. Caller must defend against missing keys when
        a given entry doesn't include all three.
    """
    if not isinstance(model_name, str):
        return None
    # Import config lazily — model_pricing is imported by token_management,
    # which is imported by monitor.lib.history, which is imported via
    # monitor.config; the lazy import keeps that chain unbothered.
    from monitor import config
    overrides = getattr(config, "MODEL_PRICING_OVERRIDES", None) or {}
    if isinstance(overrides, dict) and model_name in overrides:
        return overrides[model_name]
    return SHIPPED_MODEL_PRICING.get(model_name)


# --- F: fuel-tank budget sizing ---------------------------------------------
#
# The F: gauge's token cap is DERIVED from a dollar/day target (config.
# DAILY_COST_TARGET_USD) divided by an effective $/token rate for the current
# model + reasoning effort, so it auto-resizes when you switch model or effort.
# A STABLE per-model/effort rate is used (not the live realized rate), so the
# cap doesn't jitter within a session.

# Weights for collapsing a model's (cached-input, input, output) rates into one
# blended per-token figure. Used ONLY for the model-to-model RATIO when scaling
# the budget off a measured anchor — the assumed usage mix (cache-heavy coding:
# mostly cached input, a slice of output/reasoning) largely cancels in the
# ratio, so the absolute blend needn't be exact.
_BUDGET_BLEND_WEIGHTS = {
    "cached_input_per_token": 0.70,
    "input_per_token": 0.15,
    "output_per_token": 0.15,
}


def _blended_rate(rates):
    """Collapse a get_model_rates() dict to one per-token number via
    _BUDGET_BLEND_WEIGHTS, renormalized over whatever fields are present.
    Returns None when no usable rate field exists."""
    if not isinstance(rates, dict):
        return None
    total = 0.0
    weight = 0.0
    for key, w in _BUDGET_BLEND_WEIGHTS.items():
        r = rates.get(key)
        if isinstance(r, (int, float)) and r > 0:
            total += w * r
            weight += w
    return (total / weight) if weight > 0 else None


def _effort_multiplier():
    """Rate multiplier for the CURRENT reasoning effort, relative to medium.
    Applies only to reasoning models (REASONING_MODEL_PREFIX in config.MODEL);
    1.0 otherwise or when the effort isn't in the multiplier table."""
    from monitor import config
    model = getattr(config, "MODEL", "") or ""
    prefix = getattr(config, "REASONING_MODEL_PREFIX", "") or ""
    if not (prefix and prefix in model):
        return 1.0
    effort = getattr(config, "REASONING_EFFORT", "") or ""
    table = getattr(config, "REASONING_EFFORT_RATE_MULTIPLIER", None) or {}
    m = table.get(effort) if isinstance(table, dict) else None
    return float(m) if isinstance(m, (int, float)) and m > 0 else 1.0


def model_effective_rate_per_mtok(model=None):
    """Effective $ per 1M tokens used to size the F: budget. Precedence:
      1. measured rate in config.MODEL_TOKEN_RATE_PER_MTOK[model]
      2. anchor measured rate * (model/anchor published-price ratio)
      3. config.DEFAULT_TOKEN_RATE_PER_MTOK
    then scaled by the current reasoning-effort multiplier."""
    from monitor import config
    if model is None:
        model = getattr(config, "MODEL", "") or ""
    measured = getattr(config, "MODEL_TOKEN_RATE_PER_MTOK", None) or {}
    default_rate = getattr(config, "DEFAULT_TOKEN_RATE_PER_MTOK", 1.0) or 1.0

    base = None
    if isinstance(measured, dict) and isinstance(measured.get(model), (int, float)) and measured[model] > 0:
        base = float(measured[model])
    else:
        anchor = getattr(config, "TOKEN_RATE_ANCHOR_MODEL", None)
        anchor_rate = measured.get(anchor) if isinstance(measured, dict) else None
        if isinstance(anchor_rate, (int, float)) and anchor_rate > 0:
            bm = _blended_rate(get_model_rates(model))
            ba = _blended_rate(get_model_rates(anchor))
            if bm and ba and ba > 0:
                base = float(anchor_rate) * (bm / ba)
        if base is None:
            base = float(default_rate)

    return base * _effort_multiplier()


def session_token_budget():
    """The F: fuel-tank cap in tokens, or None to hide the gauge. Precedence:
    explicit config.SESSION_TOKEN_BUDGET override (positive int) → dollar target
    (DAILY_COST_TARGET_USD) / effective rate → None. Derived from the CURRENT
    model + effort, so it re-sizes on a switch."""
    from monitor import config
    explicit = getattr(config, "SESSION_TOKEN_BUDGET", None)
    if isinstance(explicit, (int, float)) and explicit > 0:
        return int(explicit)
    target = getattr(config, "DAILY_COST_TARGET_USD", None)
    if isinstance(target, (int, float)) and target > 0:
        rate_per_mtok = model_effective_rate_per_mtok()
        if isinstance(rate_per_mtok, (int, float)) and rate_per_mtok > 0:
            return int(target / (rate_per_mtok / 1_000_000))
    return None


def _read_usage_field(usage, *names, default=0):
    """Read the first matching field name from a usage object/dict.

    Provider response shapes vary:
      - Chat Completions: prompt_tokens, completion_tokens, prompt_tokens_details.cached_tokens
      - Responses API:    input_tokens, output_tokens
    This helper tries each name in order and returns the first non-falsy
    value (or ``default`` if none match). Handles both attribute access
    and dict access.
    """
    if usage is None:
        return default
    for name in names:
        try:
            if isinstance(usage, dict):
                val = usage.get(name)
            else:
                val = getattr(usage, name, None)
            if val is not None:
                return val
        except Exception:
            continue
    return default


def _extract_usage_tokens(response):
    """Pull ``(uncached_input_tokens, cached_tokens, output_tokens)`` from
    a response. Works across Chat Completions and Responses API shapes,
    and across dict / object responses.

    Returns ``(0, 0, 0)`` when the response has no recognizable usage
    block — caller treats that as "can't price."
    """
    if response is None:
        return 0, 0, 0
    try:
        if isinstance(response, dict):
            usage = response.get("usage")
        else:
            usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0, 0

        # Input tokens: prefer prompt_tokens (Chat Completions),
        # fall back to input_tokens (Responses API).
        prompt = _read_usage_field(usage, "prompt_tokens", "input_tokens", default=0) or 0
        # Output tokens: completion_tokens (Chat Completions),
        # output_tokens (Responses API).
        output = _read_usage_field(usage, "completion_tokens", "output_tokens", default=0) or 0

        # Cached input tokens live under prompt_tokens_details.cached_tokens
        # (Chat Completions newer shape) or input_tokens_details.cached_tokens
        # (Responses API). May be absent entirely.
        cached = 0
        for details_key in ("prompt_tokens_details", "input_tokens_details"):
            details = (
                usage.get(details_key) if isinstance(usage, dict)
                else getattr(usage, details_key, None)
            )
            if details:
                cached = _read_usage_field(details, "cached_tokens", default=0) or 0
                if cached:
                    break

        uncached_input = max(0, int(prompt) - int(cached))
        return uncached_input, int(cached), int(output)
    except Exception as e:
        logger.debug("Failed to extract usage tokens: %s", e, exc_info=True)
        return 0, 0, 0


def estimate_cost_from_usage(response, model_name):
    """Compute USD cost from a response's usage block using our pricing
    table. Returns 0.0 when we can't price the call (unknown model, no
    usable token counts).

    The estimator is the fallback that runs when litellm.completion_cost
    returns 0. It does the same math litellm would: tokens × per-model
    rates, with cached tokens billed at the cached rate.
    """
    rates = get_model_rates(model_name)
    if not rates:
        return 0.0
    uncached_input, cached, output = _extract_usage_tokens(response)
    if uncached_input == 0 and cached == 0 and output == 0:
        return 0.0
    input_rate = rates.get("input_per_token", 0.0)
    cached_rate = rates.get("cached_input_per_token", input_rate)
    output_rate = rates.get("output_per_token", 0.0)
    cost = (
        uncached_input * input_rate
        + cached * cached_rate
        + output * output_rate
    )
    return float(cost)
