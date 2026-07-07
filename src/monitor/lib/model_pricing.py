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

from monitor.lib.llm_model_utils import is_reasoning_model

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


def _blended_rate(rates, weights=None):
    """Collapse a get_model_rates() dict to one per-token number.

    Args:
        rates: Model pricing entries keyed by per-token field name.
        weights: Optional weight mapping keyed by the same field names.
            Defaults to ``_BUDGET_BLEND_WEIGHTS``.

    Returns:
        The weighted average per-token rate, renormalized over whatever
        positive-weight fields are present. Returns None when no usable
        rate field exists.
    """
    if not isinstance(rates, dict):
        return None
    resolved_weights = weights if isinstance(weights, dict) and weights else _BUDGET_BLEND_WEIGHTS
    total = 0.0
    weight = 0.0
    for key, current_weight in resolved_weights.items():
        rate = rates.get(key)
        if (
            isinstance(rate, (int, float))
            and rate > 0
            and isinstance(current_weight, (int, float))
            and current_weight > 0
        ):
            total += current_weight * rate
            weight += current_weight
    return (total / weight) if weight > 0 else None


def _calibration_defaults():
    """A fresh, zeroed per-model calibration stats dict."""
    return {
        "cost_usd": 0.0,
        "total_tokens": 0,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 0,
        "output_tokens": 0,
        "effort_weighted_tokens": 0.0,
        "effort_weight_tokens": 0,
    }


def calibration_entry(model, create=False):
    """Return the per-model calibration stats dict for ``model``.

    Stats are accumulated by ``token_management.update_token_usage`` keyed by
    the model actually used for each round-trip, so a transient single-turn
    swap to ``ADV_REASONING_MODEL`` is attributed to that model rather than
    polluting the configured default's calibration.

    Args:
        model: Model name key. Falls back to ``"(unknown)"`` when empty.
        create: When True, create (and store) a zeroed entry if absent.

    Returns:
        dict: The stored entry (created when ``create``), else a transient
        zeroed dict so read-only callers get safe defaults.
    """
    from monitor import config

    store = getattr(config, "SESSION_CALIBRATION_BY_MODEL", None)
    if not isinstance(store, dict):
        store = {}
        config.SESSION_CALIBRATION_BY_MODEL = store
    key = model if isinstance(model, str) and model else "(unknown)"
    entry = store.get(key)
    if entry is None:
        entry = _calibration_defaults()
        if create:
            store[key] = entry
    return entry


def session_empirical_pricing_mix(model=None):
    """Return empirical token-mix weights for ``model`` from accumulated usage.

    Args:
        model: Optional model name. When omitted, uses the configured model.

    Returns:
        dict: Session token totals, normalized weights, and a confidence label.
        When no composition data is available, weights are None and confidence
        remains ``"low"``.
    """
    from monitor import config

    resolved_model = model if model is not None else getattr(config, "MODEL", "") or ""
    entry = calibration_entry(resolved_model)
    cached_tokens = entry.get("cached_input_tokens", 0) or 0
    uncached_tokens = entry.get("uncached_input_tokens", 0) or 0
    output_tokens = entry.get("output_tokens", 0) or 0
    total_tokens = cached_tokens + uncached_tokens + output_tokens
    weights = None
    if total_tokens > 0:
        weights = {
            "cached_input_per_token": cached_tokens / total_tokens,
            "input_per_token": uncached_tokens / total_tokens,
            "output_per_token": output_tokens / total_tokens,
        }

    confidence = "low"
    if total_tokens >= 3_000_000:
        confidence = "high"
    elif total_tokens >= 1_000_000:
        confidence = "medium"

    return {
        "cached_input_tokens": int(cached_tokens),
        "uncached_input_tokens": int(uncached_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(total_tokens),
        "weights": weights,
        "confidence": confidence,
    }


def effort_multiplier_for(model, effort):
    """Rate multiplier for a specific reasoning effort on a specific model.

    Applies only to models whose names contain ``REASONING_MODEL_PREFIX``.
    Returns ``1.0`` for non-reasoning models or when ``effort`` is not present
    in the multiplier table.

    Args:
        model: Model name to evaluate.
        effort: Reasoning-effort label to look up in the multiplier table.

    Returns:
        float: The configured effort multiplier.
    """
    from monitor import config

    prefix = getattr(config, "REASONING_MODEL_PREFIX", "") or ""
    if not is_reasoning_model(model or "", prefix):
        return 1.0

    table = getattr(config, "REASONING_EFFORT_RATE_MULTIPLIER", None) or {}
    multiplier = table.get(effort) if isinstance(table, dict) else None
    return float(multiplier) if isinstance(multiplier, (int, float)) and multiplier > 0 else 1.0


def _effort_multiplier(model=None):
    """Rate multiplier for the CURRENT steady reasoning effort, relative to
    medium. Forward-looking: this is what sizes the live F: budget. It reflects
    only ``config.REASONING_EFFORT`` and is blind to single-turn upgrades.

    Applies only to models whose names contain ``REASONING_MODEL_PREFIX``.
    Returns ``1.0`` for non-reasoning models or when the effort is not
    present in the multiplier table.

    Args:
        model: Optional model name to evaluate. When omitted, uses the current
            configured model.

    Returns:
        float: The configured effort multiplier.
    """
    from monitor import config

    current_model = model if model is not None else getattr(config, "MODEL", "") or ""
    effort = getattr(config, "REASONING_EFFORT", "") or ""
    return effort_multiplier_for(current_model, effort)


def session_average_effort_multiplier(model=None):
    """Token-weighted average effort multiplier incurred for ``model``.

    Unlike ``_effort_multiplier`` (which reflects only the steady
    ``REASONING_EFFORT``), this folds in single-turn reasoning upgrades by
    weighting each round-trip's multiplier by that round-trip's token count.
    Backward-looking: used to normalize the observed rate back to a steady-
    effort baseline during calibration, so occasional upgrades don't bias the
    suggested ``MODEL_TOKEN_RATE_PER_MTOK`` high.

    Args:
        model: Optional model name. When omitted, uses the configured model.

    Returns:
        float | None: The weighted-average multiplier, or None when no
        effort-weighted token data has accumulated yet (callers fall back to
        the instantaneous multiplier).
    """
    from monitor import config

    resolved_model = model if model is not None else getattr(config, "MODEL", "") or ""
    entry = calibration_entry(resolved_model)
    weighted = entry.get("effort_weighted_tokens", 0.0) or 0.0
    tokens = entry.get("effort_weight_tokens", 0) or 0
    return (weighted / tokens) if (tokens > 0 and weighted > 0) else None


def effective_rate_debug_info(model=None):
    """Return detailed rate inputs used to calibrate token-rate config.

    Args:
        model: Optional model name to evaluate. When omitted, uses the current
            configured model.

    Returns:
        dict: Debug metadata including the configured calibration rate,
        anchor-derived rate, theoretical blended rate, effort multiplier,
        and final effective rate per million tokens.
    """
    from monitor import config

    resolved_model = model if model is not None else getattr(config, "MODEL", "") or ""
    raw_configured_budget_rates = getattr(config, "MODEL_TOKEN_RATE_PER_MTOK", None) or {}
    # Keep debug helpers resilient to malformed config so diagnostics still work
    # when users are investigating a broken pricing setup.
    configured_budget_rates = (
        raw_configured_budget_rates
        if isinstance(raw_configured_budget_rates, dict)
        else {}
    )
    default_rate = getattr(config, "DEFAULT_TOKEN_RATE_PER_MTOK", 1.0) or 1.0
    anchor = getattr(config, "TOKEN_RATE_ANCHOR_MODEL", None)
    configured_calibration_rate = None
    anchor_rate = configured_budget_rates.get(anchor) if isinstance(configured_budget_rates, dict) else None
    theoretical_blended_rate_per_token = _blended_rate(get_model_rates(resolved_model))
    anchor_blended_rate_per_token = _blended_rate(get_model_rates(anchor))
    empirical_mix = session_empirical_pricing_mix(resolved_model)
    empirical_blended_rate_per_token = _blended_rate(
        get_model_rates(resolved_model),
        empirical_mix["weights"],
    )
    theoretical_blended_rate = (
        theoretical_blended_rate_per_token * 1_000_000
        if isinstance(theoretical_blended_rate_per_token, (int, float))
        and theoretical_blended_rate_per_token > 0
        else None
    )
    empirical_blended_rate = (
        empirical_blended_rate_per_token * 1_000_000
        if isinstance(empirical_blended_rate_per_token, (int, float))
        and empirical_blended_rate_per_token > 0
        else None
    )
    anchor_blended_rate = (
        anchor_blended_rate_per_token * 1_000_000
        if isinstance(anchor_blended_rate_per_token, (int, float))
        and anchor_blended_rate_per_token > 0
        else None
    )
    base_rate_source = "default_token_rate"
    base_rate = float(default_rate)

    if (
        isinstance(configured_budget_rates, dict)
        and isinstance(configured_budget_rates.get(resolved_model), (int, float))
        and configured_budget_rates[resolved_model] > 0
    ):
        configured_calibration_rate = float(configured_budget_rates[resolved_model])
        base_rate = configured_calibration_rate
        base_rate_source = "configured_calibration_rate"
    elif (
        isinstance(anchor_rate, (int, float))
        and anchor_rate > 0
        and isinstance(theoretical_blended_rate, (int, float))
        and theoretical_blended_rate > 0
        and isinstance(anchor_blended_rate, (int, float))
        and anchor_blended_rate > 0
    ):
        base_rate = float(anchor_rate) * (theoretical_blended_rate / anchor_blended_rate)
        base_rate_source = "anchor_ratio"

    multiplier = _effort_multiplier(resolved_model)
    session_multiplier = session_average_effort_multiplier(resolved_model)
    effective_rate = base_rate * multiplier
    return {
        "model": resolved_model,
        "configured_calibration_rate": configured_calibration_rate,
        "configured_budget_rates": configured_budget_rates,
        "default_rate": float(default_rate),
        "anchor_model": anchor,
        "anchor_rate": anchor_rate,
        "theoretical_blended_rate": theoretical_blended_rate,
        "empirical_blended_rate": empirical_blended_rate,
        "empirical_mix": empirical_mix,
        "anchor_blended_rate": anchor_blended_rate,
        "base_rate": base_rate,
        "base_rate_source": base_rate_source,
        "effort_multiplier": multiplier,
        "session_effort_multiplier": session_multiplier,
        "effective_rate_per_mtok": effective_rate,
    }


def model_effective_rate_per_mtok(model=None):
    """Effective $ per 1M tokens used to size the F: budget.

    Args:
        model: Optional model name to evaluate. When omitted, uses the current
            configured model.

    Returns:
        float: Effective dollars per million tokens after any reasoning-effort
        multiplier is applied.
    """
    info = effective_rate_debug_info(model)
    return info["effective_rate_per_mtok"]


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
            budget = int(target / (rate_per_mtok / 1_000_000))
            return budget
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

        total = _read_usage_field(usage, "total_tokens", "total_token_count", "total", default=0) or 0
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

        prompt = int(prompt or 0)
        total = int(total or 0)
        cached = int(cached or 0)
        output = int(output or 0)

        if prompt <= 0 and total > 0 and output > 0:
            prompt = max(0, total - output)
        if output <= 0 and total > 0 and prompt > 0:
            output = max(0, total - prompt)
        if prompt <= 0 and cached > 0:
            prompt = cached
        if total > 0 and prompt > total:
            prompt = total
        if total > 0 and output > total:
            output = total
        uncached_input = max(0, prompt - cached)
        if total > 0 and uncached_input == 0 and cached > 0 and output == 0 and total > cached:
            output = max(0, total - cached)
        return uncached_input, cached, output
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
