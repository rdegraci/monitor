"""
Token management module – THE SINGLE CANONICAL API for token counting and usage tracing.
This module is the sole, official, and *mandatory* entry point for any token counting,
measurement, or update logic across the codebase.

-------------------------------------------------------------------------------------------
!! WARNING !!
NEVER use `estimate_token_count` directly, nor import it (or similar helpers)
from `lib/rate_limiter.py` or elsewhere. All token counting and updating
MUST go through the helpers provided here in this module, and nowhere else.

DO NOT invoke or wrap low-level token or usage helpers outside this module.
Any attempt to count or update tokens from non-canonical sources is considered
a violation of code maintenance, traceability, and proper auditing.

All other code (such as `history.py`, `conversation.py`, and all future code)
MUST always import token counters and update helpers exclusively from this module.
Changes to token policy, runtime auditing, or reporting should only be made here.

-------------------------------------------------------------------------------------------

This module resolves circular imports (notably between history.py and conversation.py)
and ensures all token handling is safely centralized, traceable, and auditable.
"""

import logging

from monitor import config
from monitor.lib.colors import red, reset
from monitor.lib.rate_limiter import estimate_token_count

logger = logging.getLogger(__name__)


def count_message_tokens(message):
    """
    Canonical function to count tokens in message(s).
    Use THIS function for all message token counting across the codebase—never call
    `estimate_token_count` directly!

    Accepts:
      - dict: Reads 'content' key and counts tokens for its value.
      - list/tuple: Sums token counts for each element (each element can be dict, str, or other; see below).
      - str: Counts tokens directly from the string.
      - any other type: Coerces to str and counts tokens.

    Args:
        message (dict | list | tuple | str | any): Message object(s) to count.

    Returns:
        int: Estimated token count

    Raises:
        Exception: If token counting fails
    """
    try:
        def count_single(item, idx=None):
            try:
                if isinstance(item, dict):
                    # Responses API function_call_output items use 'output' instead of 'content'.
                    if 'content' in item:
                        content = item.get('content', '')
                    elif 'output' in item:
                        content = item.get('output', '')
                    else:
                        logger.warning("Message dict missing 'content' key; treating as empty string.")
                        content = ''
                    if not isinstance(content, str):
                        logger.debug(f"Coercing non-str 'content' value to str for token counting: {type(content)}")
                        content = str(content)
                    return estimate_token_count(content)
                elif isinstance(item, str):
                    return estimate_token_count(item)
                elif hasattr(item, 'content'):
                    logger.debug("Fast-path handling object with 'content' attribute for token counting.")
                    content = item.content
                    if not isinstance(content, str):
                        logger.debug(f"Coercing non-str 'content' attribute to str for token counting: {type(content)}")
                        content = str(content)
                    return estimate_token_count(content)
                else:
                    if idx is not None:
                        logger.warning(f"Coercing non-dict/non-str message element at index {idx} to str for token counting: {type(item)}")
                    else:
                        logger.warning(f"Coercing non-dict/non-str message to str for token counting: {type(item)}")
                    return estimate_token_count(str(item))
            except Exception as inner_e:
                if idx is not None:
                    logger.error(f"Error counting tokens for element at index {idx}: {str(inner_e)}", exc_info=True)
                else:
                    logger.error(f"Error counting tokens for message: {str(inner_e)}", exc_info=True)
                raise

        if isinstance(message, (list, tuple)):
            total = 0
            for i, elem in enumerate(message):
                total += count_single(elem, idx=i)
            return total
        else:
            return count_single(message)
    except Exception as e:
        logger.error(f"Error counting message tokens: {str(e)}", exc_info=True)
        raise


def set_last_request_token_usage(last_used_tokens: int, used_estimate: bool) -> None:
    """Sets the last provider call token usage in config.

    This helper is the canonical, auditable entry point for tracking the last request's
    token usage as observed or estimated by the caller.

    Args:
        last_used_tokens (int): Token count used for the last provider call.
        used_estimate (bool): Whether the token count is an estimate (True) or a direct
            usage value from provider/SDK usage metadata (False).

    Returns:
        None
    """
    try:
        from monitor import config  # For safe circular import resolution

        if not hasattr(config, "LAST_REQUEST_TOKEN_COUNT"):
            config.LAST_REQUEST_TOKEN_COUNT = None
        if not hasattr(config, "LAST_REQUEST_USED_ESTIMATE"):
            config.LAST_REQUEST_USED_ESTIMATE = False

        config.LAST_REQUEST_TOKEN_COUNT = int(last_used_tokens)
        config.LAST_REQUEST_USED_ESTIMATE = bool(used_estimate)
    except Exception as e:
        logger.error(f"Error setting last request token usage: {str(e)}", exc_info=True)


def get_last_request_token_usage() -> tuple[int | None, bool]:
    """Gets the last provider call token usage from config.

    Reads config.LAST_REQUEST_TOKEN_COUNT and config.LAST_REQUEST_USED_ESTIMATE. If
    missing, initializes them to None and False respectively to ensure deterministic
    behavior and auditability.

    Returns:
        tuple[int|None, bool]: (last_request_token_count, last_request_used_estimate)
    """
    try:
        from monitor import config  # For safe circular import resolution

        if not hasattr(config, "LAST_REQUEST_TOKEN_COUNT"):
            config.LAST_REQUEST_TOKEN_COUNT = None
        if not hasattr(config, "LAST_REQUEST_USED_ESTIMATE"):
            config.LAST_REQUEST_USED_ESTIMATE = False

        return config.LAST_REQUEST_TOKEN_COUNT, bool(config.LAST_REQUEST_USED_ESTIMATE)
    except Exception as e:
        logger.error(f"Error getting last request token usage: {str(e)}", exc_info=True)
        return None, False


def update_history_token_count(tokens_to_add) -> int:
    """Increment ONLY ``config.TOTAL_TOKEN_COUNT`` — the live history-size
    counter used by the compaction soft-trigger and the C: indicator math.

    Use this from local message-append paths (e.g.,
    ``append_to_history_with_count``). Do NOT use it from LLM-call return
    paths — those should call ``update_token_usage(...)`` so the cost,
    ``SESSION_TOTAL_TOKENS``, ``LAST_REQUEST_TOKEN_COUNT``, and per-turn
    bucket all get updated together.

    The separation fixes a long-standing bug where appending a message to
    history was treated as an LLM call:
      - ``SESSION_TOTAL_TOKENS`` got inflated on every append, including
        the startup system message (so U: was non-zero at H:0).
      - ``LAST_REQUEST_TOKEN_COUNT`` was set to the message size even when
        no actual API request had been made yet (so L: at startup showed
        the system message size).
      - The same tokens then got counted AGAIN when the LLM call returned
        with the real ``usage.total_tokens`` — double counting on every
        turn that drifted U: 30-80% above actual API consumption.

    Args:
        tokens_to_add: Token count for the message just appended. ``None`` or
            non-numeric values are coerced to 0 with a warning.

    Returns:
        The updated value of ``config.TOTAL_TOKEN_COUNT``.
    """
    try:
        from monitor import config  # safe circular-import guard
        if not hasattr(config, "TOTAL_TOKEN_COUNT") or config.TOTAL_TOKEN_COUNT is None:
            config.TOTAL_TOKEN_COUNT = 0
        try:
            delta = int(tokens_to_add or 0)
        except (TypeError, ValueError):
            logger.warning("update_history_token_count: non-numeric input %r; using 0", tokens_to_add)
            delta = 0
        config.TOTAL_TOKEN_COUNT += delta
        return config.TOTAL_TOKEN_COUNT
    except Exception as e:
        logger.error(f"update_history_token_count failed: {e}", exc_info=True)
        return 0


def update_token_usage(tokens_or_response, *, used_estimate: bool = False, response=None, model=None):
    """
    Canonical function to update the total token count in config.TOTAL_TOKEN_COUNT.
    This is THE ONLY approved location for token count increment logic.

    Accepts either an int token count or a model response object with usage info.

    Args:
        tokens_or_response (int or object):
          int for token count, or object with `usage.total_tokens` attribute
        used_estimate (bool): True if the int was a pre-call estimate rather
          than provider-reported actual.
        response: Optional model response object used purely for cost
          computation via litellm.completion_cost. Pass the original LLM
          response when available even if you also passed extracted token
          count in `tokens_or_response`. Without this, cost cannot be
          computed and the (~$N.NN) display stays at $0.
        model: Optional name of the model that ACTUALLY produced this response,
          used as the per-model calibration key (and to price the local
          fallback). Pass this from any path that calls a model other than
          ``config.MODEL`` (e.g. commit/sub-agent generation) so its spend is
          attributed correctly. When omitted, the effective model is derived
          from ``config.MODEL`` + the per-turn reasoning override, which already
          captures the standard turn's transient ADV_REASONING_MODEL swap.

    Returns:
        int: Updated total token count
    """
    try:
        from monitor import config  # For safe circular import resolution

        # Check for TOTAL_TOKEN_COUNT as None or missing at absolute top
        if not hasattr(config, "TOTAL_TOKEN_COUNT") or getattr(config, "TOTAL_TOKEN_COUNT") is None:
            logger.warning("TOTAL_TOKEN_COUNT is missing or None at entry; initializing to 0.")
            config.TOTAL_TOKEN_COUNT = 0

        # Robust handling: Treat None argument as 0 tokens, log warning
        tokens = None
        if tokens_or_response is None:
            logger.warning("Token usage input is None; treating as 0 tokens.")
            tokens = 0
        elif hasattr(tokens_or_response, 'usage') and hasattr(tokens_or_response.usage, 'total_tokens'):
            total_tokens = tokens_or_response.usage.total_tokens
            if total_tokens is None:
                logger.warning("Token usage in response is None; treating as 0 tokens.")
                tokens = 0
            else:
                tokens = total_tokens
                try:
                    set_last_request_token_usage(int(tokens), used_estimate=False)
                except Exception:
                    logger.error("Failed to set last request token usage from response usage", exc_info=True)
            # Cost computation handled below alongside the int-path so a
            # single block covers both call conventions.
        elif isinstance(tokens_or_response, (int, float)):
            tokens = int(tokens_or_response)
            try:
                set_last_request_token_usage(tokens, used_estimate=used_estimate)
            except Exception:
                logger.error("Failed to set last request token usage from explicit token input", exc_info=True)
        else:
            # If it's not an int/float and doesn't have usage info, skip the update
            logger.warning(f"Invalid token input type: {type(tokens_or_response)}, skipping update")
            try:
                return config.TOTAL_TOKEN_COUNT if getattr(config, "TOTAL_TOKEN_COUNT", None) is not None else 0
            except Exception:
                logger.error("Failed to access TOTAL_TOKEN_COUNT after invalid input", exc_info=True)
                return 0

        # Store current count for error recovery
        try:
            current_count = config.TOTAL_TOKEN_COUNT
        except Exception:
            logger.error("Failed to read current TOTAL_TOKEN_COUNT", exc_info=True)
            current_count = 0

        # Ensure tokens is not None before performing addition
        tokens_to_add = 0 if tokens is None else tokens

        # Cost computation. Accept the response either as the primary arg
        # (when it's a model response object) or via the `response=` kwarg
        # (when the caller already extracted tokens but still has the
        # response in scope). Wrapped in its own try/except so litellm
        # failures (unknown model, stale rates, malformed response) NEVER
        # break the token-counting path. Cost is an estimate — caching
        # discounts aren't reliably visible to litellm — and resets on
        # set_model() and :reset_history.
        cost_response = None
        if response is not None:
            cost_response = response
        elif hasattr(tokens_or_response, "usage"):
            cost_response = tokens_or_response
        if cost_response is not None:
            try:
                import litellm
                from monitor.lib.llm_model_utils import resolve_turn_model

                # The model actually used for this round-trip — used to price the
                # fallback correctly and to attribute calibration data to the
                # right model. An explicit `model` argument is authoritative (for
                # callers that ran a non-default model). Otherwise derive from
                # config.MODEL + the per-turn override, which reproduces the
                # standard turn's transient ADV_REASONING_MODEL swap.
                if isinstance(model, str) and model:
                    effective_model = model
                else:
                    effective_model = resolve_turn_model(
                        getattr(config, "MODEL", "") or "",
                        getattr(config, "ADV_REASONING_MODEL", None),
                        bool(getattr(config, "CURRENT_TURN_REASONING_OVERRIDE", None)),
                        getattr(config, "REASONING_MODEL_PREFIX", "") or "",
                    )
                try:
                    cost = litellm.completion_cost(completion_response=cost_response)
                except Exception:
                    cost = 0
                # Fallback: when litellm doesn't know the model (returns 0
                # or raises), use our local pricing table. The same
                # tokens-times-rates math, just sourced from
                # config.MODEL_PRICING_OVERRIDES (YAML-supplied) or
                # SHIPPED_MODEL_PRICING. Keeps the U: cost annotation
                # honest on custom/private/new-release models.
                if not (isinstance(cost, (int, float)) and cost > 0):
                    try:
                        from monitor.lib.model_pricing import estimate_cost_from_usage
                        cost = estimate_cost_from_usage(cost_response, effective_model)
                    except Exception:
                        logger.debug("Local pricing fallback failed", exc_info=True)
                        cost = 0
                if isinstance(cost, (int, float)) and cost > 0:
                    current_cost = getattr(config, "SESSION_COST_USD", 0.0) or 0.0
                    config.SESSION_COST_USD = current_cost + float(cost)
                    # Per-model calibration cost for :fuel_debug's observed rate.
                    try:
                        from monitor.lib.model_pricing import calibration_entry
                        calibration_entry(effective_model, create=True)["cost_usd"] += float(cost)
                    except Exception:
                        logger.debug("Failed to accumulate per-model cost", exc_info=True)
                    # Also add to the current turn's bucket so the U:
                    # indicator can show recent-window and last-turn costs.
                    # If TURN_COSTS_USD is empty (e.g., LLM call happened
                    # before any user message somehow), seed an entry so the
                    # spend isn't dropped on the floor. Defensive: cost
                    # tracking must never block the LLM-call return path.
                    try:
                        turn_costs = getattr(config, "TURN_COSTS_USD", None)
                        if not isinstance(turn_costs, list):
                            turn_costs = []
                        if not turn_costs:
                            turn_costs.append(0.0)
                        turn_costs[-1] = turn_costs[-1] + float(cost)
                        config.TURN_COSTS_USD = turn_costs
                    except Exception:
                        logger.debug("Failed to accumulate per-turn cost", exc_info=True)
                try:
                    from monitor.lib.model_pricing import (
                        _extract_usage_tokens,
                        calibration_entry,
                        effort_multiplier_for,
                    )

                    uncached_input, cached_input, output_tokens = _extract_usage_tokens(cost_response)
                    # All calibration stats are attributed to the effective model
                    # so a single-turn swap to ADV_REASONING_MODEL never pollutes
                    # the configured default's rate calibration.
                    entry = calibration_entry(effective_model, create=True)
                    if uncached_input > 0:
                        entry["uncached_input_tokens"] += int(uncached_input)
                    if cached_input > 0:
                        entry["cached_input_tokens"] += int(cached_input)
                    if output_tokens > 0:
                        entry["output_tokens"] += int(output_tokens)

                    # Token-weighted effort multiplier so calibration can fold in
                    # single-turn reasoning upgrades. The effort that actually drove
                    # this round-trip is the per-turn override when set, else the
                    # steady REASONING_EFFORT (same precedence as the API call in
                    # llm_utils). Weight by the round-trip's total tokens — the base
                    # the multiplier is applied to at runtime.
                    turn_tokens = int(uncached_input) + int(cached_input) + int(output_tokens)
                    if turn_tokens > 0:
                        turn_effort = (
                            getattr(config, "CURRENT_TURN_REASONING_OVERRIDE", None)
                            or getattr(config, "REASONING_EFFORT", "")
                            or ""
                        )
                        turn_multiplier = effort_multiplier_for(effective_model, turn_effort)
                        entry["effort_weighted_tokens"] += turn_tokens * turn_multiplier
                        entry["effort_weight_tokens"] += turn_tokens
                        entry["total_tokens"] += turn_tokens
                except Exception:
                    logger.debug("Failed to accumulate session token composition", exc_info=True)
            except Exception:
                logger.debug("Failed to compute completion cost via litellm", exc_info=True)

        # Per-turn round-trip ledger: every completion accounted here is one
        # model round-trip. Mirror TURN_COSTS_USD's bucket lifecycle (a bucket
        # opens per user message in history.append) and increment the open one.
        # Counted unconditionally (not gated on cost) so unpriced calls still
        # register. Defensive: never let counting break token accounting.
        try:
            round_trips = getattr(config, "TURN_ROUND_TRIPS", None)
            if not isinstance(round_trips, list):
                round_trips = []
            if not round_trips:
                round_trips.append(0)
            round_trips[-1] = round_trips[-1] + 1
            config.TURN_ROUND_TRIPS = round_trips
        except Exception:
            logger.debug("Failed to bump TURN_ROUND_TRIPS", exc_info=True)

        # Update the count
        try:
            config.TOTAL_TOKEN_COUNT += tokens_to_add
            # Also accumulate into the pure-cumulative session counter.
            # SESSION_TOTAL_TOKENS, unlike TOTAL_TOKEN_COUNT, is never
            # overwritten by compaction paths — it reflects spend across
            # the whole session, paralleling SESSION_COST_USD. Display
            # reads from this for U so the indicator stays meaningful
            # across compactions.
            try:
                current_session = getattr(config, "SESSION_TOTAL_TOKENS", 0) or 0
                config.SESSION_TOTAL_TOKENS = current_session + tokens_to_add
            except Exception:
                logger.debug("Failed to update SESSION_TOTAL_TOKENS", exc_info=True)
            return config.TOTAL_TOKEN_COUNT
        except Exception:
            logger.error("Failed to update TOTAL_TOKEN_COUNT", exc_info=True)
            # Try to return the previous count
            try:
                return current_count
            except Exception:
                logger.error("Failed to return previous count", exc_info=True)
                return 0

    except Exception as e:
        logger.error(f"Error updating token usage: {str(e)}")
        # Final fallback
        try:
            from monitor import config
            return config.TOTAL_TOKEN_COUNT if getattr(config, "TOTAL_TOKEN_COUNT", None) is not None else 0
        except Exception:
            logger.error("Complete failure accessing config, returning 0", exc_info=True)
            return 0


def token_budgeter(params, input_window=100000, model_name=None):
    """
    Trims tool outputs (the 'output' key inside dicts of 'input', if present) adaptively
    to fit under a maximum token budget for the entire input (input_window). Trimming
    occurs only as needed and is always targeted at the largest outputs, waterfall-style,
    until the overall budget is met or no outputs can be further truncated.

    When truncating a tool's 'output', a truncation marker of the form
    ``...[TRUNCATED to input token budget <input_window>]`` will be appended to the
    trimmed output (if space allows). The marker is also counted in the
    token budget: content will be trimmed enough for the marker to fit, always leaving at
    least one content token before the marker if possible. If the marker wouldn't fit
    alongside any content, the output is replaced by only the marker. The marker is only
    added if actual truncation has occurred (original token count > new count).

    No top-level field truncation or removal is performed. Only per-tool output trimming
    occurs. All truncations and initial/final token counts are logged for audit and trace.

    Args:
        params (dict): Parameters dict potentially containing an 'input' field (list of
            tool invocations).
        input_window (int): Hard token budget for the entire input, all tools included.
        model_name (str, optional): Model type hint for tiktoken encoder if needed.

    Returns:
        dict: The modified params, with tool output fields trimmed as necessary to meet
        the token budget. If params['input'] is missing or not a proper list of dicts
        with 'output', returns the original params.
    """
    import copy
    import tiktoken

    TRUNC_MARKER = f"...[TRUNCATED to input token budget {input_window}]"

    params = copy.deepcopy(params)

    try:
        if model_name:
            from monitor.lib.llm_model_utils import get_model_head

            # Tiktoken model prefix to encoding
            encoding_model = get_model_head(
                str(model_name),
                {
                    "gpt-5.1": "gpt-5",
                    "gpt-5": "gpt-5",
                    "gpt-4.1": "gpt-4.1",
                    "gpt-4o": "gpt-4o",
                    "gpt-4": "gpt-4",
                    "o4-mini": "o4-mini"
                }
            )
            if encoding_model:
                encoder = tiktoken.encoding_for_model(encoding_model)
            else:
                encoder = tiktoken.get_encoding("cl100k_base")
        else:
            encoder = tiktoken.get_encoding("cl100k_base")
    except Exception as e:
        logger.error(
            f"No tiktoken encoder for model: {model_name} ({e}), using fallback."
        )
        encoder = tiktoken.get_encoding("cl100k_base")

    def tokens_of(obj):
        try:
            s = obj if isinstance(obj, str) else str(obj)
            return len(encoder.encode(s))
        except Exception as e:
            logger.error(
                f"Token counting failure for object {type(obj)}: {e} - treating as 0 tokens."
            )
            return 0

    def total_tokens(p):
        total = 0
        try:
            input_list = p.get("input")
        except Exception:
            return 0
        if isinstance(input_list, list):
            for elm in input_list:
                if isinstance(elm, dict):
                    for key in ("output", "content", "text", "message"):
                        if key in elm:
                            total += tokens_of(elm.get(key))
                            break
                elif isinstance(elm, str):
                    total += tokens_of(elm)
                else:
                    # Skip non-dict, non-str elements
                    continue
        return total

    def truncate_with_marker(s, max_tokens):
        try:
            # Encode content and marker once each
            content_tokens = encoder.encode(s)
            marker_tokens = encoder.encode(TRUNC_MARKER)
            marker_len = len(marker_tokens)

            # Fits as-is
            if len(content_tokens) <= max_tokens:
                return s, False

            # Nothing allowed
            if max_tokens == 0:
                return "", True

            # If not enough space for at least one content token plus marker,
            # choose deterministic fallback.
            if max_tokens < (marker_len + 1):
                if max_tokens >= marker_len:
                    return TRUNC_MARKER, True
                else:
                    return "\u2026", True

            # Reserve space for the marker and include as many content tokens as allowed
            allowed = max_tokens - marker_len  # >= 1 by prior check
            k = min(len(content_tokens), allowed)
            final_tokens = content_tokens[:k] + marker_tokens
            decoded = encoder.decode(final_tokens)
            return decoded, True
        except Exception as e:
            logger.error(
                f"Truncation failure for object {type(s)}: {e} - returning marker fallback.",
                exc_info=True
            )
            try:
                if max_tokens == 0:
                    return "", True
                marker_tokens = encoder.encode(TRUNC_MARKER)
                if max_tokens >= len(marker_tokens):
                    return TRUNC_MARKER, True
                return "\u2026", True
            except Exception:
                return "\u2026", True

    # Only per-tool-output truncation inside "input" field if present and properly structured,
    # and only iteratively as needed to reach the input_window budget.
    if (
        "input" not in params
        or not isinstance(params["input"], list)
        or not any(isinstance(elm, dict) and "output" in elm for elm in params["input"])
    ):
        logger.debug(
            "Token budgeting: params['input'] missing or not a list of dicts with 'output'. Returning original params."
        )
        return params

    input_list = params["input"]

    original_tokens = total_tokens(params)
    logger.debug(
        f"Token budgeting: initial token count is {original_tokens}. Input window: {input_window} tokens."
    )

    # Iterative trimming of largest 'output' until under input_window token budget
    def find_largest_output(input_list):
        max_len = -1
        max_i = None
        for i, elm in enumerate(input_list):
            if isinstance(elm, dict) and "output" in elm:
                output_val = elm["output"]
                toklen = tokens_of(output_val)
                if toklen > max_len and toklen > 1:
                    max_len = toklen
                    max_i = i
        return max_i, max_len

    trim_iteration = 0
    while total_tokens(params) > input_window:
        i, largest_len = find_largest_output(input_list)
        if i is None or largest_len <= 1:
            logger.debug(
                "No remaining tool outputs can be further trimmed to reduce below input_window."
            )
            break
        trim_iteration += 1
        tokentotal = total_tokens(params)
        tokens_over = tokentotal - input_window
        output_val = input_list[i]["output"]
        output_str = output_val if isinstance(output_val, str) else str(output_val)
        # Compute max allowed tokens for this output (while not going below input_window)
        needed_cut = min(tokens_over, largest_len - 1)  # Must have at least 1 token left
        new_len = largest_len - needed_cut
        new_len = max(1, new_len)
        truncated, did_truncate = truncate_with_marker(output_str, new_len)
        if did_truncate:
            logger.warning(
                f"Trimming tool output in params['input'][{i}]['output'] to fit input_window "
                f"on iteration {trim_iteration}: from {largest_len} to <= {new_len} tokens "
                f"with marker applied (total tokens before: {tokentotal}, input_window: {input_window}, "
                f"tokens over: {tokens_over})"
            )
            input_list[i]["output"] = truncated
        else:
            input_list[i]["output"] = truncated
    final_tokens = total_tokens(params)
    logger.info(
        f"Token budgeting: final token count after per-tool-output trimming is {final_tokens} (input_window: {input_window})."
    )

    return params
