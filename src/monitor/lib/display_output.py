# NOTE: No direct or legacy token counting or usage estimation logic exists in this file. 
# If token logic is required in the future, use count_message_tokens and update_token_usage from monitor.lib/token_management.py. 

import logging
import math
import os
import sys
from datetime import datetime

from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import MarkdownLexer

from monitor import config
from monitor.lib.colors import blue, red, reset, yellow

logger = logging.getLogger(__name__)

def _format_dollars(value, cumulative):
    """Format a dollar amount for the U: indicator.

    Cumulative slot (the leading "(~$total)"): 3 decimals below $1 (so
    sub-dollar single-call costs like $0.012 stay legible), 2 decimals at
    or above $1.

    Per-turn slots: 4 decimals below $1 (per-turn spend is often pennies,
    and 2 decimals would round $0.04 to $0.04 vs $0.0034 to "$0.00"), 2
    decimals at or above $1.
    """
    if cumulative:
        return f"{value:.3f}" if value < 1.0 else f"{value:.2f}"
    return f"{value:.4f}" if value < 1.0 else f"{value:.2f}"


def _fuel_color(remaining_percent):
    """Color for the F: fuel gauge by how full the tank is: blue (healthy) →
    yellow (under half) → red (nearly empty / overrun)."""
    if remaining_percent < 15:
        return red
    if remaining_percent < 50:
        return yellow
    return blue


def _context_color(remaining_tokens, remaining_percent):
    """Pick the color for the C: indicator based on how much input window
    is left. Tied to ``config.AUTO_COMPACT_THRESHOLD_RATIO`` so the color
    thresholds auto-tune to the user's compaction policy:

      - yellow fires when remaining_percent drops below the compaction
        threshold (i.e., the harness is about to compact)
      - red fires at half the yellow threshold (compaction may have failed
        or we're close to the model's hard input-window ceiling)

    Examples (with default ratio 0.30):
      yellow_threshold = (1 - 0.30) * 100 = 70%
      red_threshold    = 70% / 2          = 35%

    Examples (user's appdir ratio 0.50):
      yellow_threshold = (1 - 0.50) * 100 = 50%
      red_threshold    = 50% / 2          = 25%

    A literal zero remaining always renders red. The previous behavior
    (blue when non-zero, red when zero) is preserved as the green/normal
    case (anything above the yellow threshold stays blue)."""
    if remaining_tokens == 0:
        return red
    try:
        compact_ratio = getattr(config, "AUTO_COMPACT_THRESHOLD_RATIO", 0.30) or 0.30
        yellow_threshold_pct = (1 - compact_ratio) * 100
        red_threshold_pct = yellow_threshold_pct / 2
        if remaining_percent < red_threshold_pct:
            return red
        if remaining_percent < yellow_threshold_pct:
            return yellow
    except Exception:
        # If anything goes sideways, fall back to the historical blue.
        pass
    return blue


def print_colored_error(message):
    print(f"{red}{message}{reset}", file=sys.stderr)

def print_colored_info(message):
    print(f"{yellow}{message}{reset}", file=sys.stderr)

def display_query_result(output_string, update_history_count=None):
    """Highlight and display the result of a query.

    Args:
        output_string (str): The string to display.
        update_history_count (callable, optional): If provided, will be called to update history count.
    """
    logger.debug("Displaying query result for input...")
    if output_string is not None and not isinstance(output_string, str):
        logger.warning(f"display_query_result received non-string output: {type(output_string).__name__}")
    highlightMarkdown(output_string)
    if update_history_count is not None:
        update_history_count()

def highlightMarkdown(query_result):
    if query_result is None:
        print(f"\n{red}No query result.{reset}")
        return
    if not isinstance(query_result, str):
        try:
            logger.debug(f"highlightMarkdown received non-string output: {type(query_result).__name__}")
        except Exception:
            pass
        return
    highlighted_output = highlight(query_result, MarkdownLexer(), TerminalFormatter(reset=True))
    print(f"\n{yellow}STX{reset}")
    print(f"{highlighted_output}{yellow}ETX{reset}\n")
    print("*******************")
    print("*******************")
    print("*******************")
    print("Generated:", datetime.now().strftime("%Y-%m-%d %H:%M:%S\n"))

def format_prompt_display(conversation_count, tokens_remaining, cwd=None, model=None, extra_history_str="", context_remaining=None, rate_remaining=None, total_used=None, last_used=None, last_used_estimated: bool | None = None, context_budget=None, history_tokens=None):
    """Format the prompt display for the CLI.

    Args:
        conversation_count (int): Current conversation history count.
        tokens_remaining (int): Number of tokens remaining in allocation (backward compatible).
        cwd (str, optional): Current working directory; if None, will attempt to use os.getcwd().
        model (str, optional): The model name to display.
        extra_history_str (str): Extra string to include about history (optional).
        context_remaining (int, optional): Context remaining; if None, derived from tokens_remaining.
        rate_remaining (int, optional): Rate limiter remaining; if None, derived from monitor.lib.rate_limiter.RATE_LIMITER when available.
        total_used (int, optional): Total usage; if None, uses config.TOTAL_TOKEN_COUNT when available.
        last_used (int, optional): Last request token usage; if None, uses config.LAST_REQUEST_TOKEN_COUNT when available.
        last_used_estimated (bool | None, optional): Whether last_used is an estimate; if None, uses config.LAST_REQUEST_USED_ESTIMATE when available.

    Returns:
        str: The formatted prompt display string.
    """
    try:
        # H: renders in the default terminal color. Yellow elsewhere in the
        # indicator means "noteworthy" (cost over threshold, context low);
        # a permanently-yellow message count was decoration that read as a
        # warning. If something about H: is actually noteworthy — e.g.,
        # compactions have fired — the "(N)" prefix below carries that
        # signal explicitly.
        tch_count = str(conversation_count)
    except Exception as e:
        tch_count = "Error in calculating conversation history count"
        logger.error(f"Error: {e}", exc_info=True)

    c_count = ""
    r_count = ""
    u_count = ""
    l_count = ""
    f_count = ""

    # F: fuel tank — budget minus cumulative tokens used. The draining
    # counterpart to U:; only goes down (and may go negative). Shown as the
    # EXACT remaining token count plus percent, e.g. "5198195 (52%)" (no
    # shorthand, no price). The cap is derived from the dollar/day target per
    # current model + effort (or an explicit override); None disables the gauge.
    try:
        from monitor.lib.model_pricing import session_token_budget
        budget = session_token_budget()
        if isinstance(budget, (int, float)) and budget > 0:
            used = total_used if isinstance(total_used, (int, float)) else (
                getattr(config, "SESSION_TOTAL_TOKENS", 0) or 0
            )
            remaining = int(budget - used)
            remaining_percent = (remaining / budget) * 100
            fuel_color = _fuel_color(remaining_percent)
            # "100%" only when the tank is genuinely full (nothing used). Once
            # it dips, show 2 decimals so the slow drain on a large budget is
            # visible — TRUNCATED (not rounded) so a barely-used tank never
            # rounds back up to "100.00%".
            if remaining >= budget:
                pct_str = "100%"
            else:
                pct_str = f"{math.floor(remaining_percent * 100) / 100:.2f}%"
            f_count = f"{fuel_color}{remaining} ({pct_str}){reset}"
    except Exception as e:
        f_count = ""
        logger.error(f"Error in calculating fuel budget: {e}", exc_info=True)

    try:
        if context_remaining is None:
            context_remaining = tokens_remaining

        if context_remaining is not None:
            if context_remaining < 0:
                try:
                    logger.warning(f"Negative context_remaining detected in prompt: {context_remaining}. Total tokens: {config.TOTAL_TOKEN_COUNT}, Max allowed: {config.MAX_TOKEN_COUNT}")
                    # Print a snippet of recent conversation history if available
                    if hasattr(config, 'CONVERSATION_HISTORY') and len(config.CONVERSATION_HISTORY) >= 2:
                        logger.warning(f"Recent conversation history (last 2): {config.CONVERSATION_HISTORY[-2:]}")
                except Exception as log_err:
                    print(f"Error logging negative context_remaining: {log_err}")
            
            # Calculate percentage remaining. Prefer the caller-supplied
            # `context_budget` (typically MODEL_INPUT_WINDOW so the percent
            # matches the input-side gate the send path enforces); fall back
            # to MAX_TOKEN_COUNT for callers that don't pass it.
            try:
                budget = context_budget if isinstance(context_budget, int) and context_budget > 0 else getattr(config, 'MAX_TOKEN_COUNT', None)
                if budget and budget > 0:
                    remaining_percent = (context_remaining / budget) * 100
                    context_color = _context_color(context_remaining, remaining_percent)
                    c_count = f"{context_color}{context_remaining} ({remaining_percent:.0f}%){reset}"
                else:
                    context_color = red if context_remaining == 0 else blue
                    c_count = f"{context_color}{context_remaining}{reset}"
            except Exception:
                context_color = red if context_remaining == 0 else blue
                c_count = f"{context_color}{context_remaining}{reset}"
    except Exception as e:
        c_count = "Error in calculating context count"
        logger.error(f"Error: {e}", exc_info=True)

    try:
        if rate_remaining is None:
            try:
                from monitor.lib.rate_limiter import RATE_LIMITER
                try:
                    limit = getattr(RATE_LIMITER, 'limit', None)
                    # `current_usage` is a method (`get_current_usage()`),
                    # not an attribute. The prior code did
                    # `getattr(RATE_LIMITER, 'current_usage', None)` which
                    # always returned None and silently disabled this
                    # fallback. Call the real API.
                    current = None
                    get_current = getattr(RATE_LIMITER, 'get_current_usage', None)
                    if callable(get_current):
                        current = get_current()
                    if limit is not None and current is not None:
                        rate_remaining = limit - current
                except Exception:
                    pass
            except Exception:
                pass

        if rate_remaining is not None:
            rate_color = red if rate_remaining == 0 else blue
            r_count = f"{rate_color}{rate_remaining}{reset}"
    except Exception as e:
        r_count = "Error in calculating rate limiter remaining"
        logger.error(f"Error: {e}", exc_info=True)

    try:
        if total_used is None:
            try:
                total_used = getattr(config, 'TOTAL_TOKEN_COUNT', None)
            except Exception:
                total_used = None

        if total_used is not None:
            # U: is the cumulative-tokens-consumed counter. 0 is the
            # normal startup state, not an alarm — render in the same
            # blue as every other value. (Previously this was red on 0,
            # back when local appends inflated SESSION_TOTAL_TOKENS so
            # 0 meant "something broke during startup." That bug is
            # fixed; the red-on-zero rule outlived its reason.)
            used_color = blue
            u_count = f"{used_color}{total_used}{reset}"
            # Optional cost estimate after U. Controlled by config.SHOW_COST_ESTIMATE
            # (default True if unset in YAML). The tilde signals "estimate" —
            # cache hits and provider-specific pricing quirks make the number
            # accurate to roughly ±20%. Resets on set_model().
            try:
                if getattr(config, "SHOW_COST_ESTIMATE", True):
                    session_cost = getattr(config, "SESSION_COST_USD", 0.0) or 0.0
                    if session_cost > 0:
                        # The U cost annotation has three labeled slots:
                        #   (~T:$total W:$last-N-turns P:$previous-turn)
                        # T = Total (cumulative, ~ marks it as an estimate)
                        # W = Window sum over the last RECENT_TURN_WINDOW turns
                        # P = Previous turn (most recently completed)
                        # Labels let slots collapse without making position
                        # ambiguous — "(~T:$2.11 P:$0.24)" is unambiguous;
                        # "(~$2.11 $0.24)" could mean total+window or
                        # total+previous depending on which collapsed.
                        cost_str = _format_dollars(session_cost, cumulative=True)

                        # Per-turn slots are gated on > 0. A bucket can be
                        # exactly zero because litellm couldn't price the
                        # call (model not in its pricing table) or because
                        # the cost rounded to floor. Either way, "$0.0000"
                        # is misleading — it suggests the turn was free,
                        # not unpriced. Better to omit than mislead.
                        recent_str = ""
                        last_str = ""
                        try:
                            turn_costs = getattr(config, "TURN_COSTS_USD", None) or []
                            window = getattr(config, "RECENT_TURN_WINDOW", 10) or 10
                            # Color thresholds (USD). P uses single-turn cost;
                            # W uses per-turn average over the window so a
                            # single expensive turn doesn't immediately drive
                            # W red — it has to be sustained.
                            cost_p_yellow = getattr(config, "COST_P_YELLOW", 0.30) or 0.30
                            cost_p_red = getattr(config, "COST_P_RED", 0.80) or 0.80
                            cost_w_yellow = getattr(config, "COST_W_YELLOW", 0.30) or 0.30
                            cost_w_red = getattr(config, "COST_W_RED", 0.60) or 0.60
                            if turn_costs:
                                recent_window = turn_costs[-window:]
                                recent_sum = sum(recent_window)
                                # Show the window slot only when it carries new
                                # information vs the cumulative. Until enough
                                # turns have accumulated that older buckets
                                # actually fall outside the window, recent_sum
                                # equals session_cost — repeating the same
                                # number is visual noise. Epsilon (half a cent)
                                # absorbs floating-point jitter and catches the
                                # case where rounded display values would tie.
                                if recent_sum > 0 and abs(recent_sum - session_cost) > 0.005:
                                    w_per_turn = recent_sum / max(1, len(recent_window))
                                    if w_per_turn >= cost_w_red:
                                        w_color, w_reset = red, reset
                                    elif w_per_turn >= cost_w_yellow:
                                        w_color, w_reset = yellow, reset
                                    else:
                                        w_color, w_reset = "", ""
                                    recent_str = (
                                        f" {w_color}W:${_format_dollars(recent_sum, cumulative=False)}{w_reset}"
                                    )
                                last_val = turn_costs[-1]
                                if last_val > 0:
                                    if last_val >= cost_p_red:
                                        p_color, p_reset = red, reset
                                    elif last_val >= cost_p_yellow:
                                        p_color, p_reset = yellow, reset
                                    else:
                                        p_color, p_reset = "", ""
                                    last_str = (
                                        f" {p_color}P:${_format_dollars(last_val, cumulative=False)}{p_reset}"
                                    )
                        except Exception:
                            # If anything goes sideways, fall back to the
                            # cumulative-only annotation — never crash on
                            # display formatting.
                            recent_str = ""
                            last_str = ""

                        u_count = f"{u_count} (~T:${cost_str}{recent_str}{last_str})"
            except Exception:
                # Cost annotation must never break the prompt display.
                logger.debug("Failed to format SESSION_COST_USD", exc_info=True)
    except Exception as e:
        u_count = "Error in calculating total usage"
        logger.error(f"Error: {e}", exc_info=True)

    try:
        if last_used is None:
            try:
                last_used = getattr(config, 'LAST_REQUEST_TOKEN_COUNT', None)
            except Exception:
                last_used = None

        if last_used_estimated is None:
            try:
                last_used_estimated = getattr(config, 'LAST_REQUEST_USED_ESTIMATE', None)
            except Exception:
                last_used_estimated = None

        if last_used is not None:
            if last_used == 0:
                last_color = red
            else:
                last_color = yellow if last_used_estimated else blue
            l_count = f"{last_color}{last_used}{reset}"
    except Exception as e:
        l_count = "Error in calculating last request usage"
        logger.error(f"Error: {e}", exc_info=True)

    if cwd is None:
        try:
            cwd = os.getcwd()
        except Exception as e:
            cwd = "Error in getting current working directory"
            logger.error(f"Error: {e}", exc_info=True)

    model_str = f"{model}" if model is not None else ""

    prefix = getattr(config, 'REASONING_MODEL_PREFIX', '')
    effort = getattr(config, 'REASONING_EFFORT', '')
    reasoning_str = effort if isinstance(model, str) and prefix and (prefix in model) else ""

    parts = []
    if f_count:
        parts.append(f"F:{f_count}")
    if c_count:
        parts.append(f"C:{c_count}")
    if r_count:
        parts.append(f"R:{r_count}")
    if u_count:
        parts.append(f"U:{u_count}")
    if l_count:
        parts.append(f"L:{l_count}")
    # H indicator: "H:<count>" — the retained-history message count (tight, no
    # space after colon, to match C:/R:/U:/L:). When one or more auto-compactions
    # have fired this session, a "(N)" PREFIX leads, right after the colon:
    # "H:(N) <count>" — surfacing compaction activity at a glance. Finally, when
    # history_tokens is supplied, the retained-history TOKEN size follows in
    # parens "(<n>)" — that's the context actually re-sent each request (system
    # prompt + kept messages), i.e. the cost-relevant baseline.
    # Example: "H:(1) 29 (12084)"; with no compactions: "H:36 (16561)".
    _compaction_count = getattr(config, "SESSION_COMPACTION_COUNT", 0) or 0
    _compaction_prefix = f"({_compaction_count}) " if _compaction_count > 0 else ""
    _history_tokens_suffix = ""
    if isinstance(history_tokens, (int, float)) and history_tokens >= 0:
        _history_tokens_suffix = f" ({int(history_tokens)})"
    parts.append(f"H:{_compaction_prefix}{tch_count}{_history_tokens_suffix}{extra_history_str}")

    # RT: model round-trips in the previous turn (last TURN_ROUND_TRIPS bucket).
    # Read alongside P:: high RT + high P → many generations; low RT + high P →
    # fat (high-reasoning) calls. Omitted until a turn has registered one.
    try:
        _round_trips = getattr(config, "TURN_ROUND_TRIPS", None) or []
        if _round_trips and isinstance(_round_trips[-1], (int, float)) and _round_trips[-1] > 0:
            parts.append(f"RT:{int(_round_trips[-1])}")
    except Exception as e:
        logger.error(f"Error rendering RT round-trip count: {e}", exc_info=True)

    stats_str = " ".join(parts)

    return f"\n{cwd}\n{stats_str}\nmonitor {model_str} {reasoning_str} ]] "
