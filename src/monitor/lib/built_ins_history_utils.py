"""History and session helper commands for built-in command dispatch."""

import copy
import json
import logging
import os
import time
from typing import Any

from monitor.lib.llm_model_utils import is_reasoning_model
from monitor.lib.model_pricing import (
    _BUDGET_BLEND_WEIGHTS,
    effective_rate_debug_info,
    model_effective_rate_per_mtok,
    session_token_budget,
)
from monitor import config
from monitor.lib.display_output import print_colored_error
from monitor.lib.session_artifact_sync import sync_session_artifacts
from monitor.lib.session_artifacts import ensure_session_folder, seed_session_artifacts
from monitor.lib.system_prompt import build_system_prompt, clear_project_instructions_cache

logger = logging.getLogger(__name__)


def log_spend_summary() -> None:
    """Emit a session-scoped spend summary to the standard log.

    Returns:
        None.
    """
    try:
        # Responses-chain cost-tier rollup: what fraction of Responses requests
        # this session were billed at/above the long-context 2x cliff
        # (RESPONSES_CHAIN_TIER_TOKENS). See docs/cache/RESPONSES_CHAIN_BREAK.md.
        _tier_crossings = int(getattr(config, "SESSION_TIER_CROSSINGS", 0) or 0)
        _responses_requests = int(getattr(config, "SESSION_RESPONSES_REQUESTS", 0) or 0)
        _over_tier_pct = (
            100.0 * _tier_crossings / _responses_requests
            if _responses_requests > 0
            else 0.0
        )
        logger.info(
            "[SPEND][SUMMARY] compactions=%s skips=%s failures=%s fallbacks=%s summary_tokens_total=%s memory_calls=%s memory_skips=%s memory_stores=%s memory_nulls=%s memory_failures=%s helper_calls=%s oversize_tool_outputs=%s trimmed_tool_tokens=%s tier_crossings=%s responses_requests=%s over_tier_pct=%.1f",
            int(getattr(config, "SESSION_COMPACTION_COUNT", 0) or 0),
            int(getattr(config, "SESSION_SPEND_COMPACTION_SKIPS", 0) or 0),
            int(getattr(config, "SESSION_SPEND_COMPACTION_FAILURES", 0) or 0),
            int(getattr(config, "SESSION_SPEND_COMPACTION_FALLBACKS", 0) or 0),
            int(getattr(config, "SESSION_SPEND_SUMMARY_TOKENS_TOTAL", 0) or 0),
            int(getattr(config, "SESSION_SPEND_MEMORY_CALLS", 0) or 0),
            int(getattr(config, "SESSION_SPEND_MEMORY_SKIPS", 0) or 0),
            int(getattr(config, "SESSION_SPEND_MEMORY_STORES", 0) or 0),
            int(getattr(config, "SESSION_SPEND_MEMORY_NULLS", 0) or 0),
            int(getattr(config, "SESSION_SPEND_MEMORY_FAILURES", 0) or 0),
            int(getattr(config, "SESSION_SPEND_HELPER_CALLS", 0) or 0),
            int(getattr(config, "SESSION_SPEND_OVERSIZE_TOOL_OUTPUTS", 0) or 0),
            int(getattr(config, "SESSION_SPEND_TOOL_OUTPUT_TOKENS_TRIMMED", 0) or 0),
            _tier_crossings,
            _responses_requests,
            _over_tier_pct,
        )
    except Exception:
        logger.exception("Failed to emit [SPEND][SUMMARY] log line")


def reset_conversation_history_command(
    arg: Any | None = None,
    *,
    emit_notice: bool = True,
) -> None:
    """Reset conversation state to a freshly-started session baseline.

    Args:
        arg: Ignored dispatcher argument.
        emit_notice: When True, print the user-facing reset confirmation.

    Returns:
        None.
    """
    del arg
    try:
        clear_project_instructions_cache()

        config.CONVERSATION_HISTORY.clear()
        session_id = str(getattr(config, "SESSION_ID", "session") or "session")
        timestamp_prefix = getattr(config, "STARTUP_TIME", None) or time.strftime("%Y%m%d_%H_%M")
        paths = ensure_session_folder(timestamp_prefix, session_id)
        seed_session_artifacts(paths, session_id)
        config.CONVERSATION_HISTORY.append(
            {
                "role": "system",
                "content": build_system_prompt(
                    session_id=getattr(config, "SESSION_ID", None),
                    session_folder=paths.folder,
                ),
            }
        )
        sync_session_artifacts(paths)
        config.TOTAL_TOKEN_COUNT = 0
        config.SESSION_TOTAL_TOKENS = 0
        config.SESSION_COST_USD = 0.0
        # Clear the per-model calibration store so :fuel_debug doesn't mix a
        # reset T:/U: against stale composition/effort data from the old session.
        config.SESSION_CALIBRATION_BY_MODEL = {}
        config.SESSION_COMPACTION_COUNT = 0
        config.SESSION_SPEND_COMPACTION_SKIPS = 0
        config.SESSION_SPEND_COMPACTION_FAILURES = 0
        config.SESSION_SPEND_COMPACTION_FALLBACKS = 0
        config.SESSION_SPEND_SUMMARY_TOKENS_TOTAL = 0
        config.SESSION_SPEND_LAST_COMPACTION_TS = None
        config.SESSION_SPEND_MEMORY_CALLS = 0
        config.SESSION_SPEND_MEMORY_SKIPS = 0
        config.SESSION_SPEND_MEMORY_STORES = 0
        config.SESSION_SPEND_MEMORY_NULLS = 0
        config.SESSION_SPEND_MEMORY_FAILURES = 0
        config.SESSION_SPEND_HELPER_CALLS = 0
        config.SESSION_SPEND_OVERSIZE_TOOL_OUTPUTS = 0
        config.SESSION_SPEND_TOOL_OUTPUT_TOKENS_TRIMMED = 0
        config.SESSION_TOOL_CALL_COUNT = 0
        config.SESSION_LOOP_DETECTOR_TRIPS = 0
        # Responses-chain cost-tier telemetry: a fresh session has no prior
        # billed request. Seed LAST_BILLED_INPUT_TOKENS with the rebuilt history's
        # size (just the system prompt) — the approximate billed input of the
        # NEXT request — so the C: gauge shows a small counting-up value
        # (e.g. C:5945 (5% 1%)) instead of dropping into the window "% remaining"
        # fallback, which reads backwards (e.g. 99%). Mirrors :break_chain.
        config.SESSION_TIER_CROSSINGS = 0
        config.SESSION_RESPONSES_REQUESTS = 0
        try:
            from monitor.lib.token_management import count_message_tokens
            config.LAST_BILLED_INPUT_TOKENS = int(
                count_message_tokens(getattr(config, "CONVERSATION_HISTORY", []) or [])
            )
        except Exception:
            config.LAST_BILLED_INPUT_TOKENS = 0
        config.TURN_COSTS_USD = []
        config.TURN_ROUND_TRIPS = []
        config.TURN_CACHED_INPUT_TOKENS = []
        config.TURN_UNCACHED_INPUT_TOKENS = []
        config.TURN_OUTPUT_TOKENS = []
        config.CURRENT_TURN_REASONING_OVERRIDE = None
        config.CURRENT_TURN_IS_COLLATION = False
        config.CURRENT_TURN_TOOL_GROUPS = set()
        config.TOOL_PROFILE_GROUP_LEASES = {}
        if hasattr(config, "RESPONSE_ID"):
            config.RESPONSE_ID = None
        if hasattr(config, "last_summary_time"):
            config.last_summary_time = time.time()
        if emit_notice:
            print("Conversation history was reset to initial system prompt.")
    except Exception as exc:
        logger.error("Failed to reset conversation history: %s", exc, exc_info=True)


def break_chain_command(arg: Any | None = None, *, emit_notice: bool = True) -> None:
    """Break the Responses API chain WITHOUT clearing conversation history.

    Clears ``config.RESPONSE_ID`` so the next request starts a fresh Responses
    chain and re-sends the (visible) conversation history inline, instead of
    reusing the provider-retained ``previous_response_id`` chain. This drops the
    billed input from the accumulated hidden chain back to the size of local
    visible history — pulling you out of the long-context 2x pricing tier — while
    preserving your working context (unlike :reset_history, which wipes it).

    Use when the ``C:`` gauge shows you at/over the 128k cost cliff.
    See docs/cache/RESPONSES_CHAIN_BREAK.md.

    Args:
        arg: Ignored dispatcher argument.
        emit_notice: When True, print a user-facing confirmation.

    Returns:
        None.
    """
    del arg
    try:
        had_chain = bool(getattr(config, "RESPONSE_ID", None))
        prior_billed = int(getattr(config, "LAST_BILLED_INPUT_TOKENS", 0) or 0)
        tier = int(getattr(config, "RESPONSES_CHAIN_TIER_TOKENS", 128000) or 128000)
        if hasattr(config, "RESPONSE_ID"):
            config.RESPONSE_ID = None
        # Instant C:-gauge confirmation. The next request re-sends visible history
        # inline, so approximate the new billed size from the current conversation
        # and update LAST_BILLED_INPUT_TOKENS now — C: drops back under the cliff
        # immediately instead of waiting a turn to self-correct. The estimate
        # excludes tool schemas / system preferences the send path adds, so it
        # slightly under-counts — fine for a display gauge; the real value lands
        # on the next request. Only done when a chain was actually broken, so the
        # no-op case doesn't clobber a genuine last-billed value.
        new_billed = None
        if had_chain:
            try:
                from monitor.lib.token_management import count_message_tokens
                new_billed = int(
                    count_message_tokens(getattr(config, "CONVERSATION_HISTORY", []) or [])
                )
                config.LAST_BILLED_INPUT_TOKENS = new_billed
            except Exception:
                logger.debug(
                    "[CHAIN-BREAK] could not estimate post-break billed size; "
                    "C: will self-correct on the next request.",
                    exc_info=True,
                )
        if emit_notice:
            if not had_chain:
                print(
                    "No active Responses chain to break; the next request already "
                    "sends full history inline. Conversation left untouched."
                )
            else:
                parts = [
                    "Responses chain broken (RESPONSE_ID cleared). Conversation "
                    "history preserved — the next request re-sends visible history "
                    "inline and starts a fresh chain."
                ]
                if prior_billed > 0:
                    over = (
                        f" (over the {tier}-token 2x cliff)"
                        if tier > 0 and prior_billed >= tier
                        else ""
                    )
                    parts.append(f"Billed input was {prior_billed} tokens{over}.")
                if new_billed is not None:
                    parts.append(
                        f"C: now reflects ~{new_billed} tokens — back in the "
                        "short-context tier."
                    )
                print(" ".join(parts))
        logger.info(
            "[CHAIN-BREAK] manual :break_chain — RESPONSE_ID cleared "
            "(had_chain=%s, prior_billed=%s, new_billed=%s, tier=%s); "
            "conversation history preserved.",
            had_chain, prior_billed, new_billed, tier,
        )
    except Exception as exc:
        logger.error("Failed to break Responses chain: %s", exc, exc_info=True)


def cost_debug_command(arg: str | None = None) -> None:
    """Dump cost-tracking state for diagnosing the ``U:`` indicator.

    Args:
        arg: Ignored dispatcher argument.

    Returns:
        None.
    """
    del arg

    session_cost = getattr(config, "SESSION_COST_USD", 0.0) or 0.0
    session_tokens = getattr(config, "SESSION_TOTAL_TOKENS", 0) or 0
    buckets = getattr(config, "TURN_COSTS_USD", None) or []
    history = getattr(config, "CONVERSATION_HISTORY", None) or []
    user_count = sum(
        1 for message in history if isinstance(message, dict) and message.get("role") == "user"
    )
    bucket_sum = sum(buckets)

    print("=== Cost-tracking debug ===")
    print(f"SESSION_COST_USD:    ${session_cost:.6f}")
    print(f"SESSION_TOTAL_TOKENS: {session_tokens}")
    print(f"User messages in history: {user_count}")
    print(f"Per-turn buckets:    {len(buckets)} (sum: ${bucket_sum:.6f})")

    if buckets:
        user_messages = [
            message
            for message in history
            if isinstance(message, dict) and message.get("role") == "user"
        ]
        print("Bucket contents (index: value  len=N  ...tail of user message):")
        for index, value in enumerate(buckets):
            marker = "  <-- ZERO" if value == 0 else ""
            content = ""
            if index < len(user_messages):
                raw = user_messages[index].get("content", "")
                if not isinstance(raw, str):
                    raw = str(raw)
                flat = raw.replace("\n", " ").strip()
                length = len(flat)
                tail = flat[-100:] if length > 100 else flat
                content = f"  len={length}  ...{tail!r}"
            print(f"  [{index:3d}]: ${value:.6f}{marker}{content}")
    else:
        print("Bucket list is empty.")

    print()
    print("--- Invariant checks ---")
    if len(buckets) == user_count:
        print(f"OK  bucket_count == user_message_count ({user_count})")
    else:
        print_colored_error(
            f"MISMATCH bucket_count={len(buckets)} but user_message_count={user_count} "
            "— bucket-open or bucket-pop is firing for the wrong messages."
        )

    drift = session_cost - bucket_sum
    if abs(drift) < 1e-9:
        print(f"OK  sum(buckets) == cumulative (${session_cost:.6f})")
    else:
        print_colored_error(
            f"DRIFT sum(buckets)=${bucket_sum:.6f} vs cumulative=${session_cost:.6f} "
            f"(delta=${drift:.6f}) — some cost grew the cumulative but missed the bucket. "
            "Likely a silent exception in the bucket-update try/except at "
            "token_management.py:255-264."
        )


def _round_rate_suggestion(rate_per_mtok: float) -> float:
    """Round a suggested effective rate to a stable config-friendly value.

    Args:
        rate_per_mtok: Raw effective dollars-per-million-token estimate.

    Returns:
        Rounded rate suitable for ``MODEL_TOKEN_RATE_PER_MTOK``.
    """
    if rate_per_mtok >= 10:
        return round(rate_per_mtok, 1)
    if rate_per_mtok >= 1:
        return round(rate_per_mtok, 2)
    return round(round(rate_per_mtok / 0.05) * 0.05, 2)


_FUEL_DEBUG_HELP = """\
=== Fuel debug — how to read this ===

WHAT THIS COMMAND IS FOR
  The F: gauge is a per-session token budget = DAILY_COST_TARGET_USD divided by
  an estimated $/1M-token rate. That rate is a guess until you calibrate it
  against real spend. This command shows where the current rate comes from and
  suggests a measured replacement for MODEL_TOKEN_RATE_PER_MTOK[<model>].

THE INPUTS (what's feeding the estimate)
  MODEL / REASONING_EFFORT     Active model and its STEADY reasoning effort.
                               Single-turn upgrades are temporary and do NOT
                               change REASONING_EFFORT.
  Reasoning model match        Whether REASONING_MODEL_PREFIX appears in the
                               model name. If true, effort multipliers apply.
  Configured calibration rate  Your current MODEL_TOKEN_RATE_PER_MTOK[model],
                               or None if unset. This is the value you're tuning.
  Base rate source             How the base rate was chosen, in precedence order:
                                 configured_calibration_rate  your config value
                                 anchor_ratio                 scaled from the
                                                              anchor model's rate
                                 default_token_rate           last-resort default
  Anchor model / rate          The model whose known rate is scaled by published
                               price ratios when you haven't set this model yet.

THE RATE ESTIMATES (three ways to price a token, least -> most trustworthy)
  Theoretical blend / 1M       Published prices blended by FIXED assumed weights
                               (cached/input/output). A pure guess; used before
                               you've run enough.
  Empirical blend / 1M         Published prices blended by YOUR session's actual
                               token mix. Better -- it knows your cache ratio.
  Observed rate / 1M           Real dollars paid / real tokens used this session.
                               The ground truth. Needs T: and U: both > 0.

EFFORT MULTIPLIERS (only for reasoning models)
  Effort multiplier (now)      Multiplier for the STEADY effort. The live F:
                               budget is sized with this -- forward-looking.
  Effort multiplier (session)  Token-weighted average actually incurred,
                               including single-turn upgrade bursts. Backward-
                               looking; used to normalize the observed rate.
  Upgrade load +X%             How much your single-turn upgrades raised cost
                               over steady effort. Big and persistent => either
                               raise steady REASONING_EFFORT or expect F: to run
                               slightly generous.
  Normalized observed rate     Observed rate divided by the SESSION multiplier,
                               recovering the steady-effort BASELINE rate -- which
                               is what MODEL_TOKEN_RATE_PER_MTOK is meant to hold
                               (runtime re-applies the multiplier on top).

CONFIDENCE
  low / medium / high          Based on tokens accumulated this session:
                               <1M low, >=1M medium, >=3M high. Treat low-
                               confidence suggestions as provisional.

THE OUTPUT
  Session fuel budget          Current F: token budget given the effective rate.
  Suggested config value       Rounded rate to paste into MODEL_TOKEN_RATE_PER_MTOK.
  Basis                        Which estimate the suggestion used. Precedence:
                               observed (>=1M tok) > empirical (>=1M) > theoretical.
  YAML                         Copy-paste-ready config line.

HOW TO CALIBRATE (the reliable recipe)
  1. Run a normal session at your STEADY effort with a representative workload
     (same kind of caching you usually get).
  2. Accumulate >= 3M tokens (aim for "high" confidence).
  3. Run :fuel_debug. Prefer a suggestion whose Basis is "observed" or
     "empirical" -- ignore "theoretical", it's just the starting guess.
  4. Paste the YAML line into MODEL_TOKEN_RATE_PER_MTOK in your config.yaml.
  5. Re-run later to refine; the more you run, the better it gets.

  Notes:
   - Your cache mix drives $/token heavily. Calibrate from a session that looks
     like your normal one, not an unusual heavy- or zero-cache run.
   - For reasoning models, calibrate the BASELINE at steady effort. The
     multiplier table scales from there; don't hand-tune the rate at high effort.
   - "Upgrade load" tells you how much auto-upgrades cost. It's diagnostic, not
     something you need to put in config.

Run ':fuel_debug' with no argument for the live readout."""


def fuel_debug_command(arg: str | None = None) -> None:
    """Dump fuel-budget state and suggest a model rate configuration value.

    Args:
        arg: Optional dispatcher argument. ``help`` (or ``-h``/``--help``/``?``)
            prints the field guide instead of the live readout.

    Returns:
        None.
    """
    if isinstance(arg, str) and arg.strip().lower() in ("help", "-h", "--help", "?"):
        print(_FUEL_DEBUG_HELP)
        return

    model = getattr(config, "MODEL", None)
    effort = getattr(config, "REASONING_EFFORT", None)
    prefix = getattr(config, "REASONING_MODEL_PREFIX", None)
    # Session-wide totals (shown for context; they include any ADV_REASONING_MODEL
    # swap turns). Calibration uses the PER-MODEL entry for the active model so a
    # single-turn swap never pollutes its observed rate.
    session_cost = getattr(config, "SESSION_COST_USD", 0.0) or 0.0
    session_tokens = getattr(config, "SESSION_TOTAL_TOKENS", 0) or 0
    from monitor.lib.model_pricing import calibration_entry
    cal = calibration_entry(model)
    model_cost = cal.get("cost_usd", 0.0) or 0.0
    model_tokens = cal.get("total_tokens", 0) or 0
    observed_rate = None
    if model_cost > 0 and model_tokens > 0:
        observed_rate = model_cost / model_tokens * 1_000_000
    observed_confidence = "low"
    if model_tokens >= 3_000_000:
        observed_confidence = "high"
    elif model_tokens >= 1_000_000:
        observed_confidence = "medium"

    rate_info = effective_rate_debug_info(model)
    theoretical_blended_rate = rate_info["theoretical_blended_rate"]
    empirical_blended_rate = rate_info["empirical_blended_rate"]
    empirical_mix = rate_info["empirical_mix"]
    empirical_weights = empirical_mix["weights"]
    empirical_confidence = empirical_mix["confidence"]
    multiplier = rate_info["effort_multiplier"]
    session_multiplier = rate_info["session_effort_multiplier"]
    effective_rate = model_effective_rate_per_mtok(model)
    budget = session_token_budget()
    anchor = rate_info["anchor_model"]
    anchor_rate = rate_info["anchor_rate"]
    configured_calibration_rate = rate_info["configured_calibration_rate"]
    base_rate_source = rate_info["base_rate_source"]
    reasoning_model_match = is_reasoning_model(model, prefix)

    # Normalize by the session-average multiplier when available so occasional
    # single-turn upgrades don't bias the recovered baseline high; fall back to
    # the instantaneous multiplier before any effort-weighted data exists.
    has_session_multiplier = isinstance(session_multiplier, (int, float)) and session_multiplier > 0
    norm_multiplier = session_multiplier if has_session_multiplier else multiplier

    normalized_observed_rate = observed_rate
    if reasoning_model_match and isinstance(observed_rate, (int, float)) and norm_multiplier > 0:
        normalized_observed_rate = observed_rate / norm_multiplier

    norm_label = "session-average" if has_session_multiplier else "current"
    suggestion_basis = "configured calibration rate"
    suggestion_rate = configured_calibration_rate
    used_normalized_observed_rate = False
    if (
        isinstance(normalized_observed_rate, (int, float))
        and normalized_observed_rate > 0
        and model_tokens >= 1_000_000
    ):
        suggestion_basis = (
            f"observed U:/T: normalized by {norm_label} multiplier ({observed_confidence} confidence)"
            if reasoning_model_match
            else f"observed U:/T: ({observed_confidence} confidence)"
        )
        suggestion_rate = normalized_observed_rate
        used_normalized_observed_rate = reasoning_model_match
    elif (
        isinstance(empirical_blended_rate, (int, float))
        and empirical_blended_rate > 0
        and empirical_mix["total_tokens"] >= 1_000_000
    ):
        suggestion_basis = f"empirical blended rate ({empirical_confidence} confidence)"
        suggestion_rate = empirical_blended_rate
    elif isinstance(theoretical_blended_rate, (int, float)) and theoretical_blended_rate > 0:
        suggestion_basis = "theoretical blended rate"
        suggestion_rate = theoretical_blended_rate
    elif isinstance(effective_rate, (int, float)) and effective_rate > 0 and multiplier > 0:
        suggestion_basis = "effective rate divided by current multiplier"
        suggestion_rate = effective_rate / multiplier

    rounded_suggestion = None
    if isinstance(suggestion_rate, (int, float)) and suggestion_rate > 0:
        rounded_suggestion = _round_rate_suggestion(float(suggestion_rate))

    print("=== Fuel debug ===")
    print(f"MODEL:                    {model}")
    print(f"REASONING_EFFORT:        {effort}")
    print(f"REASONING_MODEL_PREFIX:  {prefix}")
    print(f"Reasoning model match:   {reasoning_model_match}")
    print(f"Configured calibration rate: {configured_calibration_rate!r}")
    print(f"Base rate source:        {base_rate_source}")
    print(f"Anchor model:            {anchor!r}")
    print(f"Anchor rate:             {anchor_rate!r}")
    print(
        "Heuristic blend weights:  "
        f"cached={_BUDGET_BLEND_WEIGHTS['cached_input_per_token']:.2f} "
        f"input={_BUDGET_BLEND_WEIGHTS['input_per_token']:.2f} "
        f"output={_BUDGET_BLEND_WEIGHTS['output_per_token']:.2f}"
    )
    print(f"Theoretical blend:       {theoretical_blended_rate!r}")
    print(
        "Empirical session tokens: "
        f"cached={empirical_mix['cached_input_tokens']} "
        f"input={empirical_mix['uncached_input_tokens']} "
        f"output={empirical_mix['output_tokens']} "
        f"total={empirical_mix['total_tokens']}"
    )
    print(f"Empirical confidence:    {empirical_confidence}")
    if empirical_weights is None:
        print("Empirical blend weights: unavailable")
    else:
        print(
            "Empirical blend weights: "
            f"cached={empirical_weights['cached_input_per_token']:.4f} "
            f"input={empirical_weights['input_per_token']:.4f} "
            f"output={empirical_weights['output_per_token']:.4f}"
        )
    print(f"Empirical blend / 1M:    {empirical_blended_rate!r}")
    print(f"Effort multiplier (now):     {multiplier!r}")
    if has_session_multiplier:
        print(f"Effort multiplier (session): {session_multiplier:.4f}")
        if multiplier > 0:
            upgrade_pct = (session_multiplier / multiplier - 1) * 100
            weight_tokens = cal.get("effort_weight_tokens", 0) or 0
            print(
                f"Upgrade load:            +{upgrade_pct:.1f}% over steady effort "
                f"(over {weight_tokens} effort-weighted tokens)"
            )
    else:
        print("Effort multiplier (session): unavailable (no effort-weighted tokens yet)")
    print(f"Effective rate / 1M:     {effective_rate!r}")
    print(f"Session fuel budget:     {budget!r}")
    print(f"SESSION_COST_USD (T:):   ${session_cost:.6f}  (session-wide, all models)")
    print(f"SESSION_TOTAL_TOKENS (U:): {session_tokens}  (session-wide, all models)")
    print(f"Model calibration cost:  ${model_cost:.6f}  (this model only)")
    print(f"Model calibration tokens: {model_tokens}  (this model only)")
    if observed_rate is None:
        print("Observed rate / 1M:      unavailable (need this model's cost & tokens > 0)")
    else:
        print(
            f"Observed rate / 1M:      {observed_rate:.6f} ({observed_confidence} confidence)"
        )
    if (
        reasoning_model_match
        and isinstance(normalized_observed_rate, (int, float))
        and normalized_observed_rate > 0
    ):
        print(
            "Normalized observed rate / 1M: "
            f"{normalized_observed_rate:.6f} "
            f"(divided by {norm_label} multiplier; assumes the multiplier table is correct)"
        )

    # Problem-state checks — the fuel analogue of cost_debug's invariant checks.
    # Routed through print_colored_error (stderr) so they stand out without
    # scattering the stdout dump above.
    if budget is None:
        print_colored_error(
            "WARN  Session fuel budget is None — F: gauge is hidden. Set "
            "DAILY_COST_TARGET_USD (and a usable rate) or SESSION_TOKEN_BUDGET."
        )
    if (
        observed_rate is None
        and empirical_blended_rate is None
        and theoretical_blended_rate is None
    ):
        print_colored_error(
            "WARN  No rate estimate available from any source — pricing data is "
            "missing for this model. Suggestions will fall back to defaults."
        )
    if (
        isinstance(observed_rate, (int, float))
        and observed_rate > 0
        and isinstance(empirical_blended_rate, (int, float))
        and empirical_blended_rate > 0
        # Only meaningful when the empirical blend reflects real session
        # composition; without it, empirical falls back to the theoretical
        # blend and the comparison would be a false alarm.
        and empirical_weights is not None
    ):
        divergence = abs(observed_rate - empirical_blended_rate) / empirical_blended_rate
        if divergence > 0.25:
            print_colored_error(
                f"WARN  Observed rate ({observed_rate:.4f}) and empirical blend "
                f"({empirical_blended_rate:.4f}) differ by {divergence * 100:.0f}% — "
                "published prices may be stale or the token mix is shifting; treat "
                "the suggestion as provisional."
            )

    print()
    print("--- Suggested calibration entry for MODEL_TOKEN_RATE_PER_MTOK ---")
    if rounded_suggestion is None:
        print("No suggestion available yet.")
        return
    print(f"Basis: {suggestion_basis}")
    print(f"Suggested raw rate / 1M: {float(suggestion_rate):.6f}")
    print(f"Suggested config value:  {rounded_suggestion}")
    if used_normalized_observed_rate:
        print(
            f"Note: normalized by the {norm_label} multiplier; assumes the "
            "reasoning multiplier table is correct."
        )
    if isinstance(model, str) and model:
        print(f"YAML: {model}: {rounded_suggestion}")


def dump_metrics_command(arg: str | None = None) -> None:
    """Write session metrics as JSON to a path.

    Args:
        arg: Output path.

    Returns:
        None.
    """
    path = (arg or "").strip()
    if not path:
        print_colored_error(
            "Usage: : (or /) dump_metrics <path>  — writes session metrics as JSON to <path>."
        )
        return

    expanded = os.path.abspath(os.path.expanduser(path))
    parent = os.path.dirname(expanded) or "."
    if not os.path.isdir(parent):
        print_colored_error(f"Parent directory does not exist: {parent}. Create it first.")
        return

    history = getattr(config, "CONVERSATION_HISTORY", None) or []
    user_msg_count = sum(
        1 for message in history if isinstance(message, dict) and message.get("role") == "user"
    )

    payload = {
        "schema_version": 1,
        "written_at": time.time(),
        "session_id": getattr(config, "SESSION_ID", None),
        "model": getattr(config, "MODEL", None),
        "startup_time": getattr(config, "STARTUP_TIME", None),
        "session_cost_usd": float(getattr(config, "SESSION_COST_USD", 0.0) or 0.0),
        "session_total_tokens": int(getattr(config, "SESSION_TOTAL_TOKENS", 0) or 0),
        "total_token_count": int(getattr(config, "TOTAL_TOKEN_COUNT", 0) or 0),
        "last_request_token_count": int(getattr(config, "LAST_REQUEST_TOKEN_COUNT", 0) or 0),
        "turn_costs_usd": list(getattr(config, "TURN_COSTS_USD", []) or []),
        "turn_round_trips": list(getattr(config, "TURN_ROUND_TRIPS", []) or []),
        "session_tool_call_count": int(getattr(config, "SESSION_TOOL_CALL_COUNT", 0) or 0),
        "session_loop_detector_trips": int(
            getattr(config, "SESSION_LOOP_DETECTOR_TRIPS", 0) or 0
        ),
        "session_compaction_count": int(
            getattr(config, "SESSION_COMPACTION_COUNT", 0) or 0
        ),
        "conversation_length": len(history),
        "user_message_count": user_msg_count,
    }

    try:
        with open(expanded, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, indent=2, sort_keys=True)
            file_handle.write("\n")
    except OSError as exc:
        print_colored_error(f"Failed to write metrics to {expanded}: {exc}")
        return

    print(f"Wrote metrics to {expanded}")


def dump_history_command(arg: str | None = None) -> None:
    """Write the full conversation history as JSON to a path.

    Args:
        arg: Output path.

    Returns:
        None.
    """
    path = (arg or "").strip()
    if not path:
        print_colored_error(
            "Usage: : (or /) dump_history <path>  — writes conversation history as JSON to <path>."
        )
        return

    expanded = os.path.abspath(os.path.expanduser(path))
    parent = os.path.dirname(expanded) or "."
    if not os.path.isdir(parent):
        print_colored_error(f"Parent directory does not exist: {parent}. Create it first.")
        return

    history = getattr(config, "CONVERSATION_HISTORY", None) or []
    history_copy = copy.deepcopy(list(history))

    payload = {
        "schema_version": 1,
        "written_at": time.time(),
        "session_id": getattr(config, "SESSION_ID", None),
        "model": getattr(config, "MODEL", None),
        "conversation": history_copy,
    }

    try:
        with open(expanded, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, indent=2, default=str)
            file_handle.write("\n")
    except OSError as exc:
        print_colored_error(f"Failed to write history to {expanded}: {exc}")
        return

    print(f"Wrote conversation history ({len(history_copy)} messages) to {expanded}")


def _format_elapsed(seconds: float) -> str:
    """Render a positive elapsed-time delta as a short human string.

    Args:
        seconds: Elapsed seconds.

    Returns:
        Human-readable relative age string.
    """
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def load_history_command(arg: str | None = None) -> None:
    """Replace current conversation history with a saved transcript.

    Args:
        arg: Input path.

    Returns:
        None.
    """
    path = (arg or "").strip()
    if not path:
        print_colored_error(
            "Usage: : (or /) load_history <path>  — load a saved conversation JSON."
        )
        return

    expanded = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(expanded):
        print_colored_error(f"File not found: {expanded}")
        return

    try:
        with open(expanded, "r", encoding="utf-8") as file_handle:
            envelope = json.load(file_handle)
    except json.JSONDecodeError as exc:
        print_colored_error(f"Failed to parse {expanded} as JSON: {exc}")
        return
    except OSError as exc:
        print_colored_error(f"Failed to read {expanded}: {exc}")
        return

    if not isinstance(envelope, dict):
        print_colored_error(
            f"{expanded}: expected a JSON object envelope, got {type(envelope).__name__}. "
            "Was this file written by :dump_history?"
        )
        return

    schema = envelope.get("schema_version")
    if schema != 1:
        print_colored_error(
            f"{expanded}: schema_version={schema!r}, expected 1. "
            "This file may have been written by a future version of monitor."
        )
        return

    conversation = envelope.get("conversation")
    if not isinstance(conversation, list):
        print_colored_error(
            f"{expanded}: 'conversation' must be a list, got "
            f"{type(conversation).__name__}."
        )
        return

    prior_count = len(getattr(config, "CONVERSATION_HISTORY", []) or [])
    config.CONVERSATION_HISTORY.clear()
    config.CONVERSATION_HISTORY.extend(conversation)
    config.TOTAL_TOKEN_COUNT = 0
    config.SESSION_TOTAL_TOKENS = 0
    config.SESSION_COST_USD = 0.0
    config.SESSION_COMPACTION_COUNT = 0
    config.SESSION_TOOL_CALL_COUNT = 0
    config.SESSION_LOOP_DETECTOR_TRIPS = 0
    config.TURN_COSTS_USD = []
    config.TURN_ROUND_TRIPS = []
    config.TURN_CACHED_INPUT_TOKENS = []
    config.TURN_UNCACHED_INPUT_TOKENS = []
    config.TURN_OUTPUT_TOKENS = []
    config.CURRENT_TURN_REASONING_OVERRIDE = None
    config.CURRENT_TURN_IS_COLLATION = False
    config.CURRENT_TURN_TOOL_GROUPS = set()
    config.TOOL_PROFILE_GROUP_LEASES = {}
    if hasattr(config, "RESPONSE_ID"):
        config.RESPONSE_ID = None
    if hasattr(config, "last_summary_time"):
        config.last_summary_time = time.time()

    written_at = envelope.get("written_at")
    if isinstance(written_at, (int, float)) and written_at > 0:
        elapsed = time.time() - written_at
        elapsed_str = _format_elapsed(elapsed)
        stale_warning = (
            f" Saved {elapsed_str} — tool results (file contents, listings) "
            "may be stale relative to current filesystem state."
        )
    else:
        stale_warning = ""

    src_session = envelope.get("session_id") or "(unknown)"
    src_model = envelope.get("model") or "(unknown)"
    print(
        f"Loaded {len(conversation)} messages from {expanded} "
        f"(replaced {prior_count} in current history).{stale_warning} "
        f"Source session_id={src_session!r}, original model={src_model!r}."
    )
