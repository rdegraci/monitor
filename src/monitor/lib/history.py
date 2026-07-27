# history.py
# =============================================================================
# This module manages conversation history, token counting, dynamic summarization,
# and system prompts for chat-based applications powered by LLMs (e.g., Litellm).
#
# Core responsibilities:
#  - Tracking and updating the chat history while accurately counting tokens.
#  - Enforcing conversation size, token, and memory limits by summarizing when needed.
#  - Supporting external integrations (e.g., logging, social summaries).
#  - Providing dependency injection for testing and customization.
#
# Functions are designed for clarity, extensibility, and stateful operation in
# interactive systems (CLI or server-based bots).
# =============================================================================

__all__ = [
    'append_to_history_with_count',
    'update_conversation_history',
    'append_conversation_history',
    'initialize_chat_history',
    'adjust_history_size',
    'check_limits',
    'generate_conversation_summary',
    'reset_conversation_with_summary'
]

import json
import logging
import readline
import sys
import time
from collections.abc import Callable

import litellm

from monitor import config
from monitor.lib.history_types import HistoryConfig, HistoryLogger, MessageAppender, TokenCounter, UsageUpdater

from monitor.lib import rate_limiter
# SYSTEM_PROMPT import removed — this module no longer references it directly.
# Callers that need the system prompt pass it in as a parameter
# (see append_conversation_history's system_prompt arg, etc.).
from monitor.lib.colors import blue, red, reset, yellow
from monitor.lib.token_management import (
    count_message_tokens as count_message_tokens,
    update_history_token_count as update_history_token_count,
    update_token_usage as update_token_usage,
)


def _extract_choice_message_content(choice_message):
    """Extract content from a completion choice message.

    Args:
        choice_message: Message payload returned by an LLM provider. May be an
            object with a ``content`` attribute or a dictionary with a
            ``content`` key.

    Returns:
        The extracted message content, or ``None`` when unavailable.
    """
    if isinstance(choice_message, dict):
        return choice_message.get("content")
    return getattr(choice_message, "content", None)

logger = logging.getLogger(__name__)  # Standardized to __name__

def log_negative_token_count(logger: HistoryLogger, config: HistoryConfig) -> None:
    """
    Logs explicit warnings if TOTAL_TOKEN_COUNT is negative or unexpectedly high.
    Hardened to safely handle non-integer MAX_TOKEN_COUNT/TOTAL_TOKEN_COUNT values.
    """
    if isinstance(config, dict):
        total_tokens_attr = config.get("TOTAL_TOKEN_COUNT", None)
        max_tokens_attr = config.get("MAX_TOKEN_COUNT", None)
    else:
        total_tokens_attr = getattr(config, "TOTAL_TOKEN_COUNT", None)
        max_tokens_attr = getattr(config, "MAX_TOKEN_COUNT", None)

    total_tokens = None
    max_tokens = None

    # Safely coerce TOTAL_TOKEN_COUNT
    if total_tokens_attr is not None:
        try:
            total_tokens = int(total_tokens_attr)
        except (ValueError, TypeError):
            total_tokens = None  # Skip numeric comparisons if invalid

    # Safely coerce MAX_TOKEN_COUNT
    if max_tokens_attr is not None:
        try:
            max_tokens = int(max_tokens_attr)
        except (ValueError, TypeError):
            max_tokens = None
            try:
                logger.debug(f"[TOKEN COUNT] Invalid MAX_TOKEN_COUNT value ({max_tokens_attr}); skipping comparative checks.")
            except Exception:
                logger.debug("[TOKEN COUNT] Invalid MAX_TOKEN_COUNT value; skipping comparative checks.")

    if total_tokens is not None:
        if total_tokens < 0:
            logger.error(f"[TOKEN COUNT] CRITICAL: TOTAL_TOKEN_COUNT is negative ({total_tokens})!")
        elif max_tokens is not None and total_tokens > (0.95 * max_tokens):
            logger.info(f"[TOKEN COUNT][CUMULATIVE] TOTAL_TOKEN_COUNT: ({total_tokens}) processed.")

def append_to_history_with_count(
    message: dict,
    conversation_history: list,
    count_message_tokens_func: Callable,
    update_token_usage_func: Callable,
) -> None:
    """
    Append a message to a conversation history and update token count.

    Token bookkeeping splits two ways:
      - TOTAL_TOKEN_COUNT (live history-size counter, used by compaction
        triggers and the C: indicator) — incremented by every append via
        update_history_token_count.
      - SESSION_TOTAL_TOKENS + LAST_REQUEST_TOKEN_COUNT + cost — touched
        ONLY by the LLM-call return path (update_token_usage with the
        real provider usage). Local appends never credit these. This is
        the fix for a long-standing bug where adding a message to history
        was treated as an LLM event, inflating U: at startup and double-
        counting on every turn.

    ``update_token_usage_func`` is preserved in the signature for
    backward compatibility with existing call sites but is no longer
    invoked here — it remains the canonical hook for LLM-call accounting.

    Args:
        message (dict): Message to append (role, content).
        conversation_history (list): The chat history in-place.
        count_message_tokens_func (Callable): Counts tokens in the message.
        update_token_usage_func (Callable): Retained for API compatibility;
            no longer invoked from this function.
    """
    del update_token_usage_func  # intentionally unused — see docstring above
    try:
        tokens = count_message_tokens_func(message)
        update_history_token_count(tokens)
        logger.debug(f"Appended message with {tokens} tokens to conversation_history (len={len(conversation_history)+1})")
        conversation_history.append(message)
        # When a user message lands, open a new bucket in the per-turn cost
        # ledger. All LLM calls that happen between this user message and the
        # next one will accumulate into this entry. Defensive: wrapped so a
        # missing/odd TURN_COSTS_USD state never blocks the append itself.
        try:
            if isinstance(message, dict) and message.get("role") == "user":
                turn_costs = getattr(config, "TURN_COSTS_USD", None)
                if not isinstance(turn_costs, list):
                    turn_costs = []
                turn_costs.append(0.0)
                config.TURN_COSTS_USD = turn_costs
                # Parallel per-turn round-trip ledger (see update_token_usage).
                round_trips = getattr(config, "TURN_ROUND_TRIPS", None)
                if not isinstance(round_trips, list):
                    round_trips = []
                round_trips.append(0)
                config.TURN_ROUND_TRIPS = round_trips
                turn_cached = getattr(config, "TURN_CACHED_INPUT_TOKENS", None)
                if not isinstance(turn_cached, list):
                    turn_cached = []
                turn_cached.append(0)
                config.TURN_CACHED_INPUT_TOKENS = turn_cached
                turn_uncached = getattr(config, "TURN_UNCACHED_INPUT_TOKENS", None)
                if not isinstance(turn_uncached, list):
                    turn_uncached = []
                turn_uncached.append(0)
                config.TURN_UNCACHED_INPUT_TOKENS = turn_uncached
                turn_output = getattr(config, "TURN_OUTPUT_TOKENS", None)
                if not isinstance(turn_output, list):
                    turn_output = []
                turn_output.append(0)
                config.TURN_OUTPUT_TOKENS = turn_output
        except Exception:
            logger.debug("Failed to open new turn cost/round-trip bucket on user message", exc_info=True)
    except Exception as e:
        logger.error(f"Error appending to conversation history: {str(e)}", exc_info=True)

def update_conversation_history(
    content: str,
    role: str,
    conversation_history: list,
    append_func: Callable,
    count_message_tokens_func: Callable,
    update_token_usage_func: Callable,
) -> None:
    """
    Conditionally adds a message of specified role and content to the chat history.

    Args:
        content (str): Message text.
        role (str): 'user', 'assistant', etc.
        conversation_history (list): The chat history.
        append_func (Callable): Function to append message to the history.
        count_message_tokens_func (Callable): Counts tokens in the message.
        update_token_usage_func (Callable): Updates tracked usage (side effect).
    """
    if content:
        try:
            append_func(
                {"role": role, "content": content},
                conversation_history,
                count_message_tokens_func,
                update_token_usage_func,
            )
            logger.debug(f"Updated conversation history with {role} message: '{content[:80]}'... (new len={len(conversation_history)})")
        except Exception as e:
            logger.error(f"Error appending to conversation history: {str(e)}", exc_info=True)

def append_conversation_history(
    user_input: str,
    conversation_history: list,
    conversation_logs_func: Callable,
    handle_token_limit_func: Callable,
    check_limits_func: Callable,
    generate_summary_func: Callable,
    reset_with_summary_func: Callable,
    system_prompt: str,
    config: HistoryConfig,
    post_social_summaries_func: Callable,
    logger: HistoryLogger,
) -> None:
    """
    Main entry point for storing a new user input and performing summarization if limits exceeded.

    Ensures history size/token usage do not exceed operational constraints by invoking
    summarization and reset routines as needed.

    All token counting and usage logic is routed via canonical helpers in lib/token_management.py.

    Args:
        user_input (str): New user message.
        conversation_history (list): Mutable chat history.
        conversation_logs_func (Callable): For persistently storing/logging user inputs.
        handle_token_limit_func (Callable): Adjusts token max after overflow.
        check_limits_func (Callable): Returns dict with current state vs. thresholds (see `check_limits`).
        generate_summary_func (Callable): Produces summary message from chat.
        reset_with_summary_func (Callable): Resets history to summary + user input.
        system_prompt (str): System-level chat context.
        config (object): Contains runtime state and settings.
        post_social_summaries_func (Callable): Optional posting to external systems.
        logger (object): Logger for diagnostics.
    """
    from monitor.lib.token_management import count_message_tokens, update_token_usage

    logger.debug(
        f"[APPEND_CONVERSATION_HISTORY] Pre-append: len={len(conversation_history)}, TOTAL_TOKEN_COUNT={getattr(config, 'TOTAL_TOKEN_COUNT', 'n/a')}"
    )
    try:
        # Append user message and update token count via canonical helpers
        append_to_history_with_count(
            {"role": "user", "content": user_input},
            conversation_history,
            count_message_tokens,
            update_token_usage,
        )
        logger.debug(
            f"[APPEND_CONVERSATION_HISTORY] After append: len={len(conversation_history)}, TOTAL_TOKEN_COUNT={getattr(config, 'TOTAL_TOKEN_COUNT', 'n/a')}"
        )
    except Exception as e:
        logger.error(f"Error appending to conversation history: {str(e)}", exc_info=True)
    log_negative_token_count(logger, config)
    try:
        # Update external log, if any
        conversation_logs_func(user_input)
    except Exception as e:
        logger.error(f"Error updating conversation logs: {str(e)}", exc_info=True)

    current_time = time.time()
    time_since_last_summary = (
        current_time - config.last_summary_time
        if getattr(config, "last_summary_time", None) is not None
        else None
    )
    logger.debug(
        f"[APPEND_CONVERSATION_HISTORY] About to call check_limits with TOTAL_TOKEN_COUNT={getattr(config, 'TOTAL_TOKEN_COUNT', 'n/a')}, MAX_TOKEN_COUNT={getattr(config, 'MAX_TOKEN_COUNT', 'n/a')}, len(conversation_history)={len(conversation_history)}"
    )
    # Compute actual tokens in history for accurate limit checks and diagnostics
    try:
        setattr(config, "_ACTIVE_CONVERSATION_HISTORY_FOR_LIMITS", conversation_history)
    except Exception:
        pass
    tokens_in_history = count_message_tokens(conversation_history)
    logger.debug(
        f"[APPEND_CONVERSATION_HISTORY] Token diagnostics: tokens_in_history={tokens_in_history}, config.TOTAL_TOKEN_COUNT={getattr(config, 'TOTAL_TOKEN_COUNT', 'n/a')}"
    )
    # Evaluate whether summarization or other limits are triggered
    limits = check_limits_func(
        tokens_in_history,
        config.MAX_TOKEN_COUNT,
        config.CONVERSATION_MAX_SIZE,
        conversation_history,
        config.SUMMARIZATION_CONFIG,
        logger,
        config,
        time_since_last_summary,
    )
    logger.info(
        f"[SUMMARIZATION] Limit check - triggers: {limits['trigger_reasons']}, metrics: {limits['metrics']} (should_summarize={limits['should_summarize']})"
    )

    if limits["should_summarize"]:
        logger.info(
            f"[SUMMARIZATION] Summarization triggered - Reasons: {limits['trigger_reasons']}, Current metrics: {limits['metrics']}"
        )
        soft_triggered = bool(limits["trigger_reasons"].get("tokens")) and not bool(
            limits["metrics"].get("over_token_limit", False)
        )
        if soft_triggered:
            try:
                config.SESSION_COMPACTION_COUNT = getattr(config, "SESSION_COMPACTION_COUNT", 0) + 1
            except Exception:
                logger.debug("[SUMMARIZATION] Failed to increment SESSION_COMPACTION_COUNT for soft-trigger compaction.")
        # If tokens overflowed, optionally auto-adjust token max
        if limits["trigger_reasons"]["tokens"]:
            try:
                config.MAX_TOKEN_COUNT = handle_token_limit_func(config.MAX_TOKEN_COUNT, config.TOTAL_TOKEN_COUNT)
                logger.info(
                    f"[SUMMARIZATION] Max token count possibly updated by handler: now {config.MAX_TOKEN_COUNT}"
                )
            except Exception as e:
                logger.error(f"[SUMMARIZATION] Error updating MAX_TOKEN_COUNT: {str(e)}", exc_info=True)
        # If enabled, post summaries externally (e.g., to social media or dashboards)
        if getattr(config, "EXTERNAL_SERVICES", False):
            try:
                post_social_summaries_func()
                logger.info("[SUMMARIZATION] Posted to external social summaries.")
            except Exception as e:
                logger.error(f"[SUMMARIZATION] Error posting social media summaries: {str(e)}", exc_info=True)

        # New policy: Skip summarization when Responses API adapter is active and specific model prefix + response id present.
        skip_summary = False
        try:
            responses_api_flag = getattr(config, "RESPONSES_API", False)
            reasoning_prefix = getattr(config, "REASONING_MODEL_PREFIX", "") or ""
            model_name = getattr(config, "MODEL", "") or ""
            response_id_present = getattr(config, "RESPONSE_ID", None) is not None
            if responses_api_flag and reasoning_prefix and isinstance(model_name, str) and model_name.lower().startswith(reasoning_prefix.lower()) and response_id_present:
                skip_summary = True
            logger.debug(f"[SUMMARIZATION] skip_summary evaluation: RESPONSES_API={responses_api_flag}, REASONING_MODEL_PREFIX='{reasoning_prefix}', MODEL='{model_name}', RESPONSE_ID present={response_id_present} -> skip_summary={skip_summary}")
        except Exception as e:
            logger.error(f"[SUMMARIZATION] Error evaluating skip_summary policy: {str(e)}", exc_info=True)
            skip_summary = False

        if skip_summary:
            try:
                # Truncate conversation to system prompt + last 20 non-system messages
                # (initial cap), then pre-validate against MAX_TOKEN_COUNT and drop
                # additional oldest non-system messages if the new state would still
                # overflow. The previous flow committed an over-budget post-truncation
                # state, producing the same context-length-exceeded HTTP 400 chain on
                # the next request that the summarize path also previously had.
                system_message = next((msg for msg in conversation_history if msg.get('role') == 'system'), None)
                non_system_msgs = [msg for msg in conversation_history if msg.get('role') != 'system']
                keep_last_n = 20
                kept = non_system_msgs[-keep_last_n:] if len(non_system_msgs) > keep_last_n else non_system_msgs[:]

                # Build a proposed new history without mutating conversation_history yet.
                def _build(kept_msgs):
                    out = []
                    if system_message:
                        out.append(system_message)
                    out.extend(kept_msgs)
                    return out

                new_history = _build(kept)

                # Pre-validate against MAX_TOKEN_COUNT and drop oldest non-system
                # messages while still over budget.
                max_tokens = getattr(config, "MAX_TOKEN_COUNT", None)
                token_budget_ok = True
                if isinstance(max_tokens, int) and max_tokens > 0:
                    try:
                        proposed_total = count_message_tokens(new_history)
                    except Exception:
                        logger.warning(
                            "[SUMMARIZATION] skip_summary: could not pre-validate token "
                            "budget; applying truncation without budget check.",
                            exc_info=True,
                        )
                        proposed_total = None

                    extra_dropped = 0
                    while proposed_total is not None and proposed_total > max_tokens and kept:
                        kept = kept[1:]  # drop the oldest of the kept tail
                        extra_dropped += 1
                        new_history = _build(kept)
                        try:
                            proposed_total = count_message_tokens(new_history)
                        except Exception:
                            proposed_total = None
                            break

                    if proposed_total is not None and proposed_total > max_tokens:
                        # Even with all non-system messages dropped, still over budget —
                        # the system prompt alone exceeds MAX_TOKEN_COUNT. Degenerate
                        # config; do not mutate, preserve existing history.
                        logger.critical(
                            f"[SUMMARIZATION] skip_summary: cannot fit history within "
                            f"MAX_TOKEN_COUNT ({max_tokens}); even the system prompt alone "
                            f"would exceed the budget. Preserving existing history."
                        )
                        token_budget_ok = False
                    elif extra_dropped > 0:
                        logger.warning(
                            f"[SUMMARIZATION] skip_summary: trimmed {extra_dropped} "
                            f"additional oldest message(s) beyond the last-{keep_last_n} "
                            f"window to fit MAX_TOKEN_COUNT ({proposed_total}/{max_tokens})."
                        )

                if token_budget_ok:
                    conversation_history[:] = new_history
                    try:
                        config.TOTAL_TOKEN_COUNT = count_message_tokens(conversation_history)
                    except Exception:
                        logger.error(
                            "[SUMMARIZATION] Failed to update config.TOTAL_TOKEN_COUNT "
                            "after skip-based truncation.",
                            exc_info=True,
                        )
                    logger.info(
                        f"[SUMMARIZATION] Skipped summarization due to Responses API adapter. "
                        f"Truncated history to system + {len(kept)} non-system messages "
                        f"(started from last {keep_last_n}; further trimmed to fit "
                        f"MAX_TOKEN_COUNT if needed). New len={len(conversation_history)}, "
                        f"TOTAL_TOKEN_COUNT={getattr(config, 'TOTAL_TOKEN_COUNT', 'n/a')}"
                    )
            except Exception as e:
                logger.error(f"[SUMMARIZATION] Error while truncating history when skipping summary: {str(e)}", exc_info=True)
            # Do not call generate_summary_func; return early from summarization flow.
        else:
            # Two-stage summarization to preserve as much context as possible.
            #
            # The previous implementation truncated conversation_history *in
            # place* before the summary LLM call whenever it exceeded roughly
            # half the model window. That meant the summarizer never saw the
            # dropped older messages, so the resulting "summary" was actually
            # a summary of only the recent tail — the older context was lost
            # silently. Worse, if the summary call then failed, the truncated
            # state was already committed and could not be rolled back.
            #
            # New behavior:
            #   1. First attempt: pass the FULL conversation_history to the
            #      summarizer. If the provider accepts it, the summary covers
            #      everything and no context is dropped.
            #   2. If the first attempt fails (typically because the full
            #      history exceeds the provider's input budget), fall back to
            #      summarizing a *copy* of the history truncated to fit. The
            #      copy is built by ``_build_truncated_history_copy`` and does
            #      not mutate conversation_history.
            #   3. If both attempts fail, log the failure and leave
            #      conversation_history untouched. The user can recover with
            #      :reset_history, but no silent context loss occurs.
            #
            # The reset itself is atomic and pre-validates the post-reset
            # token budget; see reset_conversation_with_summary above.

            logger.info(
                f"[SUMMARIZATION] Beginning to generate summary. Conversation messages: "
                f"{len(conversation_history)}, total_token_count: {config.TOTAL_TOKEN_COUNT}."
            )

            response = None
            summary_was_from_truncated_fallback = False
            try:
                from monitor.lib import llm_utils

                response = generate_summary_func(
                    system_prompt,
                    conversation_history,
                    config.SUMMARIZATION_CONFIG,
                    config.MODEL,
                    lambda **kwargs: llm_utils.call_litellm_completion(
                        kwargs["model"],
                        kwargs["messages"],
                        tool_descriptions=[],
                        gemini_tool_descriptions=[],
                        reasoning_effort=kwargs.get("reasoning_effort"),
                        max_completion_tokens=kwargs.get("max_completion_tokens"),
                        temperature=kwargs.get("temperature"),
                        top_p=kwargs.get("top_p"),
                        top_k=kwargs.get("top_k"),
                    ),
                    count_message_tokens,
                    rate_limiter.RATE_LIMITER,
                    logger,
                    config,
                )
            except Exception as e:
                try:
                    config.SESSION_SPEND_COMPACTION_FALLBACKS = (
                        int(getattr(config, "SESSION_SPEND_COMPACTION_FALLBACKS", 0) or 0) + 1
                    )
                except Exception:
                    logger.debug("[SPEND][COMPACTION] Failed to increment fallback counter", exc_info=True)
                logger.warning(
                    f"[SUMMARIZATION] Full-history summarization failed ({e}); "
                    f"falling back to truncated-history summarization."
                )
                truncated_copy = _build_truncated_history_copy(
                    conversation_history, config, logger
                )
                try:
                    from monitor.lib import llm_utils

                    response = generate_summary_func(
                        system_prompt,
                        truncated_copy,
                        config.SUMMARIZATION_CONFIG,
                        config.MODEL,
                        lambda **kwargs: llm_utils.call_litellm_completion(
                            kwargs["model"],
                            kwargs["messages"],
                            tool_descriptions=[],
                            gemini_tool_descriptions=[],
                            reasoning_effort=kwargs.get("reasoning_effort"),
                            max_completion_tokens=kwargs.get("max_completion_tokens"),
                            temperature=kwargs.get("temperature"),
                            top_p=kwargs.get("top_p"),
                            top_k=kwargs.get("top_k"),
                        ),
                        count_message_tokens,
                        rate_limiter.RATE_LIMITER,
                        logger,
                        config,
                    )
                    summary_was_from_truncated_fallback = True
                except Exception as e2:
                    try:
                        config.SESSION_SPEND_COMPACTION_FAILURES = (
                            int(getattr(config, "SESSION_SPEND_COMPACTION_FAILURES", 0) or 0) + 1
                        )
                    except Exception:
                        logger.debug("[SPEND][COMPACTION] Failed to increment failure counter", exc_info=True)
                    logger.error(
                        f"[SUMMARIZATION] Truncated-history fallback also failed ({e2}); "
                        f"conversation history will not be compacted this turn. "
                        f"Existing history is preserved.",
                        exc_info=True,
                    )
                    logger.info(
                        "[SPEND][COMPACTION] event=skip reason=fallback_failed model=%s pre_tokens=%s",
                        getattr(config, "MODEL", None),
                        getattr(config, "TOTAL_TOKEN_COUNT", None),
                    )
                    response = None

            summary_content = None
            summary_token_count = None
            if response is not None and hasattr(response, "choices") and len(response.choices) > 0 and hasattr(response.choices[0], "message"):
                summary_content = _extract_choice_message_content(response.choices[0].message)
                if summary_content:
                    summary_token_count = count_message_tokens(
                        {"role": "system", "content": summary_content}
                    )

            if not summary_content:
                try:
                    config.SESSION_SPEND_COMPACTION_SKIPS = (
                        int(getattr(config, "SESSION_SPEND_COMPACTION_SKIPS", 0) or 0) + 1
                    )
                except Exception:
                    logger.debug("[SPEND][COMPACTION] Failed to increment skip counter", exc_info=True)
                logger.error(
                    "[SUMMARIZATION] No usable summary produced; "
                    "conversation history will not be compacted this turn. "
                    "Existing history is preserved."
                )
                logger.info(
                    "[SPEND][COMPACTION] event=skip reason=no_summary model=%s pre_tokens=%s",
                    getattr(config, "MODEL", None),
                    getattr(config, "TOTAL_TOKEN_COUNT", None),
                )
            else:
                logger.info(
                    f"[SUMMARIZATION] Summary generated. Length: {len(summary_content)} chars, "
                    f"Estimated tokens: {summary_token_count}. "
                    f"From fallback (truncated history): {summary_was_from_truncated_fallback}. "
                    f"Snippet: '{summary_content[:200]}...'"
                )
                if summary_was_from_truncated_fallback:
                    logger.warning(
                        "[SUMMARIZATION] Note: summary was generated from a truncated subset of "
                        "history because the full history exceeded the model's input budget. "
                        "Some older context may not appear in the summary."
                    )
                if summary_token_count and summary_token_count > config.MAX_TOKEN_COUNT * 0.6:
                    logger.warning(
                        f"[SUMMARIZATION] Generated summary itself is large "
                        f"({summary_token_count} tokens, limit {config.MAX_TOKEN_COUNT}). "
                        f"Downstream truncation in reset_conversation_with_summary will "
                        f"recover if needed."
                    )
                try:
                    logger.debug(
                        f"[SUMMARIZATION] Resetting conversation history. Pre-reset: "
                        f"len={len(conversation_history)}, "
                        f"TOTAL_TOKEN_COUNT={getattr(config, 'TOTAL_TOKEN_COUNT', 'n/a')}"
                    )
                    reset_with_summary_func(
                        summary_content,
                        system_prompt,
                        user_input,
                        conversation_history,
                        append_to_history_with_count,
                        logger,
                        config,
                    )
                    config.last_summary_time = time.time()
                    post_reset_total_tokens = count_message_tokens(conversation_history)
                    log_negative_token_count(logger, config)
                    logger.info(
                        f"[SUMMARIZATION] After reset: history message count="
                        f"{len(conversation_history)}, total tokens={post_reset_total_tokens}"
                    )
                except Exception as e:
                    logger.error(
                        f"[SUMMARIZATION] Error resetting conversation with summary: {str(e)}",
                        exc_info=True,
                    )
                    logger.warning(
                        "[SUMMARIZATION] Summarization should have occurred, but conversation "
                        "was not reset properly!"
                    )
    else:
        logger.debug("[SUMMARIZATION] Summarization not triggered by limit check.")
        # Extra: warn if state size is still dangerously high even if not triggered (defensive)
        # Guard against invalid MAX_TOKEN_COUNT before using it and use configured token_threshold for comparison
        try:
            max_token_count_raw = getattr(config, 'MAX_TOKEN_COUNT', None)
            if max_token_count_raw is None:
                raise TypeError("MAX_TOKEN_COUNT is missing")
            max_token_count_value = int(max_token_count_raw)
        except Exception as e:
            logger.error("[SUMMARIZATION] Invalid or missing MAX_TOKEN_COUNT when evaluating prompt-size warning.", exc_info=True)
            raise RuntimeError("Invalid or missing MAX_TOKEN_COUNT for prompt-size warning") from e
        token_threshold = None
        try:
            token_threshold = config.SUMMARIZATION_CONFIG['triggers'].get('token_threshold')
            if token_threshold is None:
                logger.warning("[SUMMARIZATION] token_threshold missing from summarization_config, using default 0.95")
                token_threshold = 0.95
            token_threshold = float(token_threshold)
        except Exception:
            logger.error("[SUMMARIZATION] Invalid token_threshold in summarization_config; using default 0.95")
            token_threshold = 0.95
        if not 0 < token_threshold <= 1:
            logger.warning(f"[SUMMARIZATION] token_threshold ({token_threshold}) out of expected range (0-1]; using default 0.95")
            token_threshold = 0.95
        token_limit_threshold = max_token_count_value * token_threshold
        if tokens_in_history >= token_limit_threshold:
            logger.warning(
                f"[SUMMARIZATION][PROMPT] NOT TRIGGERED: But prompt token count (tokens_in_history={tokens_in_history}) is >= {int(token_threshold*100)}% of MAX_TOKEN_COUNT ({max_token_count_value})"
            )

def initialize_chat_history(
    conversation_history: list,
    append_func: Callable,
    system_prompt: str,
    history_file_path: str,
    logger: HistoryLogger,
    config: HistoryConfig,
    count_message_tokens_func: Callable,
    update_token_usage_func: Callable,
) -> str:
    """
    Loads prior readline input history (if available) and appends the base system prompt as the initial message.

    Args:
        conversation_history (list): Mutable chat messages.
        append_func (Callable): To append initial system message.
        system_prompt (str): Launch prompt.
        history_file_path (str): Where CLI/readline history is stored.
        logger (object): Diagnostics.
        config (object): Contains runtime state and settings.
        count_message_tokens_func (Callable): Counts tokens in the message.
        update_token_usage_func (Callable): Updates tracked usage (side effect).
    Returns:
        str: The path to the readline history file used.
    """
    logger.debug("Initializing chat history...")
    history_file = history_file_path
    try:
        readline.read_history_file(history_file)
        logger.debug(f"Loaded readline history from {history_file}")
    except FileNotFoundError:
        logger.debug(f"No history file found at expected location: {history_file}")
    system_message = {"role": "system", "content": f"{system_prompt}"}
    try:
        append_func(system_message, conversation_history, count_message_tokens_func, update_token_usage_func)
        logger.debug(f"Appended system prompt as first message to conversation history (len={len(conversation_history)})")
    except Exception as e:
        logger.error(f"Error appending system prompt to conversation history: {str(e)}", exc_info=True)
    return history_file

def adjust_history_size(
    new_size: int,
    conversation_history: list,
    current_max_size: int,
    print_func: Callable,
    color_warning_funcs: dict,
    logger: HistoryLogger,
    config: HistoryConfig,
) -> int:
    """
    Adjusts the maximum allowable conversation history size and trims history if needed.

    Args:
        new_size (int): Target max history size.
        conversation_history (list): Active chat log.
        current_max_size (int): Current limit.
        print_func (Callable): To relay warnings or confirmations.
        color_warning_funcs (dict): Dict containing color functions/strings.
        logger (object): Diagnostics.
        config (object): Contains runtime state and settings.
    Returns:
        int: The new or existing history size limit.
    """
    from monitor.lib.token_management import count_message_tokens

    red = color_warning_funcs.get('red', '')
    yellow = color_warning_funcs.get('yellow', '')
    reset = color_warning_funcs.get('reset', '')
    if new_size is None:
        # User just wants to view current limit
        print_func(f"Current config.CONVERSATION_MAX_SIZE: {current_max_size}")
        return current_max_size
    try:
        new_size = int(str(new_size))
        # Warn user for impractically small or large limits
        if new_size < 10:
            print_func(f"{red}Warning: Very small history size may impact conversation quality{reset}")
        elif new_size > 50:
            print_func(f"{yellow}Warning: Very large history size may impact performance{reset}")
        old_size = current_max_size
        current_max_size = new_size
        print_func(f"config.CONVERSATION_MAX_SIZE adjusted from {old_size} to {new_size}")
        try:
            # Trim history to retain only the most recent allowed messages,
            # always preserving system prompt (if any)
            if len(conversation_history) > current_max_size + 1:
                system_message = next((msg for msg in conversation_history if msg.get('role') == 'system'), None)
                orig_len = len(conversation_history)
                if system_message:
                    conversation_history[:] = [system_message] + conversation_history[-(current_max_size):]
                else:
                    conversation_history[:] = conversation_history[-(current_max_size):]
                logger.info(f"Conversation history trimmed from {orig_len} to {len(conversation_history)} messages (new max: {current_max_size})")
                print_func(f"Conversation history trimmed to {current_max_size} messages")
                # Recalculate token count after trim
                config.TOTAL_TOKEN_COUNT = count_message_tokens(conversation_history)
                logger.debug(f"Updated TOTAL_TOKEN_COUNT after trim: {config.TOTAL_TOKEN_COUNT}")
        except Exception as e:
            logger.error(f"Error trimming conversation history: {str(e)}", exc_info=True)
        return current_max_size
    except ValueError:
        print_func(f"{red}Error: Please provide a valid integer for history size{reset}")
        return current_max_size

def deep_size(obj):
    """Recursive deep size calculation for memory usage."""
    if isinstance(obj, dict):
        return sys.getsizeof(obj) + sum(deep_size(v) for v in obj.values())
    elif isinstance(obj, list):
        return sys.getsizeof(obj) + sum(deep_size(item) for item in obj)
    else:
        return sys.getsizeof(obj)



def _get_responses_chain_compaction_pressure(config, logger):
    """Estimate reserve-aware Responses chain pressure for compaction decisions.

    Args:
        config: Runtime configuration object.
        logger: Logger used for diagnostics.

    Returns:
        dict: Reserve-aware pressure metrics for chained Responses sessions.
    """
    result = {
        "enabled": False,
        "request_class": None,
        "model_input_window": None,
        "usable_window": None,
        "hidden_chain_reserve": 0,
        "payload_budget": None,
        "requires_compaction": False,
        "telemetry_request_class": None,
        "telemetry_payload_budget": None,
        "telemetry_requires_compaction": False,
    }

    responses_api_flag = getattr(config, "RESPONSES_API", False)
    previous_response_id = getattr(config, "RESPONSE_ID", None)
    conversation_history = getattr(config, "CONVERSATION_HISTORY", None)
    if not isinstance(conversation_history, list):
        conversation_history = getattr(config, "_ACTIVE_CONVERSATION_HISTORY_FOR_LIMITS", None)
    if responses_api_flag is not True or not previous_response_id or not isinstance(conversation_history, list):
        return result

    try:
        from monitor.core import llm_responses_adapter as responses_adapter

        input_window = getattr(config, "MODEL_INPUT_WINDOW", None)
        if not isinstance(input_window, int) or input_window <= 0:
            input_window = getattr(config, "MODEL_CONTEXT_WINDOW", None)
            if not isinstance(input_window, int) or input_window <= 0:
                input_window = getattr(config, "MAX_TOKEN_COUNT", None)

        telemetry_params = {
            responses_adapter.REQUEST_PARAM_MODEL: getattr(config, "MODEL", None),
            responses_adapter.REQUEST_PREV_RESPONSE_ID: previous_response_id,
            responses_adapter.REQUEST_PARAM_INPUT: conversation_history,
        }
        followup_iteration = responses_adapter.infer_followup_iteration(
            telemetry_params,
            default_iteration=0,
        )
        _telemetry_copy, telemetry_budget = responses_adapter.budget_followup_request(
            telemetry_params,
            iteration=followup_iteration,
            input_window=input_window,
        )

        latest_user_input = None
        for message in reversed(conversation_history):
            if isinstance(message, dict) and message.get("role") == "user":
                latest_user_input = message.get("content")
                break

        hard_budget = None
        hard_request_class = None
        hard_requires_compaction = False
        if latest_user_input:
            hard_params = {
                responses_adapter.REQUEST_PARAM_MODEL: getattr(config, "MODEL", None),
                responses_adapter.REQUEST_PREV_RESPONSE_ID: previous_response_id,
                responses_adapter.REQUEST_PARAM_INPUT: latest_user_input,
            }
            _hard_copy, hard_budget = responses_adapter.budget_followup_request(
                hard_params,
                iteration=followup_iteration,
                input_window=input_window,
            )
            hard_request_class = hard_budget.get("request_class")
            hard_requires_compaction = (
                hard_budget.get("decision")
                == responses_adapter.FOLLOWUP_BUDGET_DECISION_FALLBACK
            )

        result.update(
            {
                "enabled": True,
                "request_class": hard_request_class or telemetry_budget.get("request_class"),
                "model_input_window": telemetry_budget.get("model_input_window"),
                "usable_window": telemetry_budget.get("usable_window"),
                "hidden_chain_reserve": telemetry_budget.get("hidden_chain_reserve", 0),
                "payload_budget": hard_budget.get("payload_budget") if hard_budget else telemetry_budget.get("payload_budget"),
                "requires_compaction": hard_requires_compaction,
                "telemetry_request_class": telemetry_budget.get("request_class"),
                "telemetry_payload_budget": telemetry_budget.get("payload_budget"),
                "telemetry_requires_compaction": telemetry_budget.get("decision")
                == responses_adapter.FOLLOWUP_BUDGET_DECISION_FALLBACK,
            }
        )
    except Exception:
        logger.exception(
            "[CHECK_LIMITS] Failed to derive reserve-aware Responses compaction pressure"
        )
    return result

def check_limits(
    total_token_count: int,
    max_token_count: int,
    max_history_size: int,
    conversation_history: list,
    summarization_config: dict,
    logger: HistoryLogger,
    config: HistoryConfig,
    time_since_last_summary: float | None = None,
) -> dict:
    """
    Determines if any summarization or pruning triggers are met using content, time, memory, and token usage.

    All token/budget checks use canonical count_message_tokens from monitor.lib/token_management.py.

    Args:
        total_token_count (int): Running total (for this chat) of tokens.
        max_token_count (int): Trigger for summary/overflow.
        max_history_size (int): Max allowed chat log entries.
        conversation_history (list): Full history (mutable).
        summarization_config (dict): Settings for summary thresholds, triggers.
        logger (object): Diagnostics/emphasis on guiding the operator.
        config (object): Contains last_summary_time, etc.
        time_since_last_summary (float, optional): Force recalculation vs. now if not set.

    Returns:
        dict: Dict reporting all triggered limits, extra metrics, and advice.
    """
    logger.debug(
        f"[CHECK_LIMITS ENTRY] Invoked with total_token_count={total_token_count}, max_token_count={max_token_count}, "
        f"max_history_size={max_history_size}, len(conversation_history)={len(conversation_history)}, "
        f"time_since_last_summary={time_since_last_summary}"
    )

    # Defensive type coercion and validation for numeric params
    logger.debug(f"Pre-coercion types: total_token_count={type(total_token_count)}, max_token_count={type(max_token_count)}, max_history_size={type(max_history_size)}")

    # Coerce total_token_count
    try:
        total_token_count = int(total_token_count)
    except (ValueError, TypeError) as e:
        logger.error(f"[CHECK_LIMITS] Cannot coerce total_token_count to int: {str(e)}")
        raise ValueError(f"Cannot coerce total_token_count to int: {str(e)}")

    # Coerce max_token_count
    try:
        max_token_count = int(max_token_count)
    except (ValueError, TypeError) as e:
        logger.error(f"[CHECK_LIMITS] Cannot coerce max_token_count to int: {str(e)}")
        raise ValueError(f"Cannot coerce max_token_count to int: {str(e)}")

    # Coerce max_history_size
    try:
        max_history_size = int(max_history_size)
    except (ValueError, TypeError) as e:
        logger.error(f"[CHECK_LIMITS] Cannot coerce max_history_size to int: {str(e)}")
        raise ValueError(f"Cannot coerce max_history_size to int: {str(e)}")

    logger.debug(f"Post-coercion types: total_token_count={type(total_token_count)}, max_token_count={type(max_token_count)}, max_history_size={type(max_history_size)}")

    # Coerce token_threshold (ratio, so float)
    token_threshold = summarization_config['triggers'].get('token_threshold')
    if token_threshold is None:
        logger.warning("[CHECK_LIMITS] token_threshold missing from summarization_config, using default 0.95")
        token_threshold = 0.95
    try:
        token_threshold = float(token_threshold)
    except (ValueError, TypeError):
        logger.error(f"[CHECK_LIMITS] Invalid token_threshold ({token_threshold}), using default 0.95")
        token_threshold = 0.95
    if not 0 < token_threshold <= 1:
        logger.warning(f"[CHECK_LIMITS] token_threshold ({token_threshold}) out of expected range (0-1], using default 0.95")
        token_threshold = 0.95

    # Now calculate threshold safely
    token_limit_threshold = max_token_count * token_threshold
    logger.debug(f"[CHECK_LIMITS] Calculated token_limit_threshold = {token_limit_threshold} (type: {type(token_limit_threshold)})")

    if total_token_count < 0:
        logger.error("[CHECK_LIMITS] CRITICAL: Negative total_token_count computed!")
    elif max_token_count is not None and total_token_count > (2 * max_token_count):
        logger.critical("[CHECK_LIMITS] CRITICAL: total_token_count is more than double max_token_count! Likely runaway.")
    elif max_token_count is not None and total_token_count > (0.95 * max_token_count):
        logger.warning(f"[CHECK_LIMITS] Near maximum: total_token_count={total_token_count}, max_token_count={max_token_count}")
    log_negative_token_count(logger, config)
    current_time = time.time()
    if getattr(config, "last_summary_time", None) is None:
        logger.debug("[CHECK_LIMITS] No last_summary_time on config, initializing to now.")
        config.last_summary_time = current_time
    if time_since_last_summary is None:
        time_since_last_summary = current_time - config.last_summary_time
        logger.debug(f"[CHECK_LIMITS] Calculated time_since_last_summary={time_since_last_summary:.3f} (current_time={current_time}, last_summary_time={config.last_summary_time})")
    logger.debug(
        f"[CHECK_LIMITS] Calculated token_limit_threshold = {token_limit_threshold} "
        f"(max_token_count={max_token_count}, trigger_ratio={summarization_config['triggers']['token_threshold']})"
    )
    logger.info(
        f"[CHECK_LIMITS] Token thresholds: total_token_count={total_token_count}; threshold={token_limit_threshold}; max_token_count={max_token_count}; "
        f"effective_auto_compact_ratio={getattr(config, 'AUTO_COMPACT_THRESHOLD_RATIO', 'n/a')}"
    )
    over_token_limit = total_token_count > token_limit_threshold
    logger.debug(
        f"[CHECK_LIMITS] Over token limit? total_token_count={total_token_count} > token_limit_threshold={token_limit_threshold} -> {over_token_limit}"
    )
    # Sum just the length of 'content' fields for a rough measure of memory/size.
    total_content_size = sum(len(str(msg.get('content', ''))) for msg in conversation_history)
    logger.debug(
        f"[CHECK_LIMITS] total_content_size (sum content lengths) = {total_content_size}"
    )
    avg_message_size = (
        total_content_size / len(conversation_history) if conversation_history else 0
    )
    logger.debug(
        f"[CHECK_LIMITS] avg_message_size = {avg_message_size:.3f} (total_content_size={total_content_size}, n_msgs={len(conversation_history)})"
    )
    # Effective history size is set to avoid exceeding token budget with large messages
    avg_tokens_per_message = (
        total_token_count / len(conversation_history) if conversation_history else 0
    )  # Fixed: use avg_tokens_per_message for units
    if avg_tokens_per_message > 0:
        effective_history_limit = min(max_history_size, max_token_count / avg_tokens_per_message)
        logger.debug(
            f"[CHECK_LIMITS] avg_tokens_per_message > 0, so effective_history_limit = min({max_history_size}, {max_token_count} / {avg_tokens_per_message}) = {effective_history_limit:.3f}"
        )
    else:
        effective_history_limit = max_history_size
        logger.debug(
            f"[CHECK_LIMITS] avg_tokens_per_message == 0, so effective_history_limit = max_history_size = {effective_history_limit:.3f}"
        )
    over_history_limit = len(conversation_history) > effective_history_limit
    logger.debug(
        f"[CHECK_LIMITS] Over history limit? len(conversation_history)={len(conversation_history)} > effective_history_limit={effective_history_limit:.3f} -> {over_history_limit}"
    )
    time_limit_exceeded = (
        time_since_last_summary > summarization_config['triggers']['time_limit_seconds']
    )
    logger.debug(
        f"[CHECK_LIMITS] time_limit_exceeded? time_since_last_summary={time_since_last_summary} > time_limit_seconds={summarization_config['triggers']['time_limit_seconds']} -> {time_limit_exceeded}"
    )
    # System memory (in MB) for the chat history list object - Fixed: use deep_size
    current_memory_usage = deep_size(conversation_history) / (1024 * 1024)
    logger.debug(
        f"[CHECK_LIMITS] current_memory_usage = deep_size(conversation_history) / (1024*1024) = {deep_size(conversation_history)} bytes = {current_memory_usage:.6f} MB"
    )
    memory_limit_exceeded = (
        current_memory_usage > summarization_config['triggers']['memory_limit_mb']
    )
    logger.debug(
        f"[CHECK_LIMITS] memory_limit_exceeded? current_memory_usage={current_memory_usage:.6f} > memory_limit_mb={summarization_config['triggers']['memory_limit_mb']} -> {memory_limit_exceeded}"
    )
    logger.debug(
        f"[CHECK_LIMITS] avg_tokens_per_message = {avg_tokens_per_message:.3f} (total_token_count={total_token_count}, n_msgs={len(conversation_history)})"
    )
    if avg_tokens_per_message > 0:
        optimal_history_size = int(max_token_count * 0.8 / avg_tokens_per_message)
        logger.debug(
            f"[CHECK_LIMITS] Calculated optimal_history_size for ':history_size' suggestion = int({max_token_count} * 0.8 / {avg_tokens_per_message}) = {optimal_history_size}"
        )
        if optimal_history_size < max_history_size * 0.7:
            logger.info(
                f"Messages using many tokens ({avg_tokens_per_message:.1f}/msg). Consider ':history_size {optimal_history_size}'"
            )
    # Compaction policy:
    #
    # The token trigger (``over_token_limit``, derived from
    # ``token_threshold * max_token_count``) is the primary, load-bearing
    # compaction signal for visible/local history pressure. For chained
    # Responses API sessions, also consult the reserve-aware follow-up budget so
    # hidden previous_response_id context can force compaction even when the
    # visible transcript still appears to fit.
    #
    # The remaining secondary triggers (time, memory) only contribute to
    # ``should_summarize`` when token usage is also above
    # ``SECONDARY_PRESSURE_RATIO`` of ``max_token_count``.
    #
    # ``over_history_limit`` (CONVERSATION_MAX_SIZE / message-count check) is
    # NO LONGER a trigger. Token pressure handles compaction; message count
    # alone is a poor proxy for "should we compact" because it ignores
    # per-message size variance. The flag is still computed and surfaced in
    # ``trigger_reasons['history']`` for observability — callers can inspect
    # "history is at N messages" without it firing compaction.
    SECONDARY_PRESSURE_RATIO = 0.5
    under_secondary_pressure = (
        isinstance(max_token_count, int)
        and max_token_count > 0
        and total_token_count > SECONDARY_PRESSURE_RATIO * max_token_count
    )
    secondary_trigger = time_limit_exceeded or memory_limit_exceeded
    responses_chain_pressure = _get_responses_chain_compaction_pressure(config, logger)
    compaction_soft_ratio = None
    try:
        compaction_soft_ratio = config.effective_auto_compact_ratio()
    except Exception:
        compaction_soft_ratio = summarization_config['triggers'].get('token_threshold', 0.95)
    try:
        compaction_soft_ratio = float(compaction_soft_ratio)
    except (TypeError, ValueError):
        compaction_soft_ratio = 0.95
    if not 0 < compaction_soft_ratio <= 1:
        compaction_soft_ratio = 0.95

    h_based_threshold = max_token_count * compaction_soft_ratio
    over_history_tokens_limit = total_token_count > h_based_threshold
    logger.debug(
        f"[CHECK_LIMITS] H-based soft threshold = {h_based_threshold} (ratio={compaction_soft_ratio}); total_token_count={total_token_count} -> over_history_tokens_limit={over_history_tokens_limit}"
    )

    should_summarize = (
        over_token_limit
        or over_history_tokens_limit
        or (under_secondary_pressure and secondary_trigger)
        or responses_chain_pressure.get("requires_compaction", False)
    )
    logger.debug(
        f"[CHECK_LIMITS EXIT] should_summarize = {should_summarize} "
        f"(over_token_limit={over_token_limit}, "
        f"over_history_tokens_limit={over_history_tokens_limit}, "
        f"h_based_threshold={h_based_threshold}, "
        f"under_secondary_pressure={under_secondary_pressure} "
        f"(threshold={SECONDARY_PRESSURE_RATIO * max_token_count if isinstance(max_token_count, int) else 'n/a'}), "
        f"over_history_limit={over_history_limit}, "
        f"time_limit_exceeded={time_limit_exceeded}, "
        f"memory_limit_exceeded={memory_limit_exceeded}, "
        f"responses_chain_requires_compaction={responses_chain_pressure.get('requires_compaction')}, "
        f"responses_chain_payload_budget={responses_chain_pressure.get('payload_budget')}, "
        f"responses_chain_hidden_chain_reserve={responses_chain_pressure.get('hidden_chain_reserve')}, "
        f"responses_chain_telemetry_requires_compaction={responses_chain_pressure.get('telemetry_requires_compaction')}, "
        f"responses_chain_telemetry_payload_budget={responses_chain_pressure.get('telemetry_payload_budget')})"
    )
    if over_token_limit:
        logger.info(
            f"[CHECK_LIMITS] Token limit triggered: total_token_count={total_token_count} > token_limit_threshold={token_limit_threshold}"
        )
    if over_history_limit:
        logger.info(
            f"[CHECK_LIMITS] History limit triggered: len(conversation_history)={len(conversation_history)} > effective_history_limit={effective_history_limit:.3f}"
        )
    if time_limit_exceeded:
        logger.info(
            f"[CHECK_LIMITS] Time limit triggered: time_since_last_summary={time_since_last_summary:.3f} > time_limit_seconds={summarization_config['triggers']['time_limit_seconds']}"
        )
    if memory_limit_exceeded:
        logger.info(
            f"[CHECK_LIMITS] Memory limit triggered: current_memory_usage={current_memory_usage:.6f} MB > memory_limit_mb={summarization_config['triggers']['memory_limit_mb']} MB"
        )
    if not any([
        over_token_limit,
        over_history_limit,
        time_limit_exceeded,
        memory_limit_exceeded,
        responses_chain_pressure.get("requires_compaction", False),
    ]):
        logger.debug(
            "[CHECK_LIMITS] No summarization triggers activated. All thresholds respected."
        )
    logger.debug("[CHECK_LIMITS EXIT] Returning metrics and trigger_reasons.")
    return {
        'should_summarize': should_summarize,
        'trigger_reasons': {
            'tokens': over_token_limit,
            'history': over_history_limit,
            'time': time_limit_exceeded,
            'memory': memory_limit_exceeded,
            'responses_chain_budget': responses_chain_pressure.get('requires_compaction', False),
        },
        'metrics': {
            'token_count': total_token_count,
            'token_limit': token_limit_threshold,
            'history_size': len(conversation_history),
            'history_limit': effective_history_limit,
            'memory_usage_mb': current_memory_usage,
            'responses_chain_payload_budget': responses_chain_pressure.get('payload_budget'),
            'responses_chain_hidden_chain_reserve': responses_chain_pressure.get('hidden_chain_reserve'),
            'responses_chain_request_class': responses_chain_pressure.get('request_class'),
        }
    }

def generate_conversation_summary(
    system_prompt: str,
    conversation_history: list,
    summarization_config: dict,
    model_name: str,
    completion_func: Callable,
    count_message_tokens_func: Callable,
    rate_limiter_obj: object,
    logger: HistoryLogger,
    config: HistoryConfig,
) -> object:
    """
    Requests a summary of the chat conversation from the language model API,
    using constraints to manage token budgets and API limits.

    All summary token estimation/counting is handled using canonical helpers from monitor.lib/token_management.py.

    Args:
        system_prompt (str): Summary framing for the model.
        conversation_history (list): Full conversation to summarize.
        summarization_config (dict): Contains the LLM prompt template, thresholds.
        model_name (str): Name/id for the LM backend.
        completion_func (Callable): LLM API client (such as litellm.completion).
        count_message_tokens_func (Callable):  Canonical message token counting helper (lib/token_management.py).
        rate_limiter_obj (object): To throttle requests as needed.
        logger (object): For diagnostics and warnings.
        config (object): The live config object (read MAX_TOKEN_COUNT directly).

    Uses summary_token_ratio from monitor.config (via summarization_config['triggers']['summary_token_ratio']) to limit maximum summary length. If not set, defaults to 0.5. The maximum allowed summary tokens will be computed as:
        max_summary_tokens = int(config.MAX_TOKEN_COUNT * summarization_config['triggers'].get('token_reduction_factor', 0.7) * summarization_config['triggers'].get('summary_token_ratio', 0.5))
    This will be passed to completion_func as max_tokens. A warning is logged if the ratio is missing from monitor.config.
    
    Returns:
        object: The raw completion/response object from the LLM.
    """
    messages = [msg for msg in conversation_history if msg.get('content')]
    try:
        logger.info(
            f"[SUMMARIZATION] Starting to generate LLM summary: {len(messages)} messages, first 100 chars: '{str(messages)[:100]}'"
        )
        estimated_tokens = sum(count_message_tokens_func(m) for m in messages)
        logger.info(f"[SUMMARIZATION] Estimated tokens to summarize: {estimated_tokens}")
        log_negative_token_count(logger, config)
        if hasattr(rate_limiter_obj, "wait_if_needed"):
            rate_limiter_obj.wait_if_needed(estimated_tokens)

        triggers = summarization_config.get('triggers', {})
        token_reduction_factor = triggers.get('token_reduction_factor', 0.7)
        summary_token_ratio = triggers.get('summary_token_ratio', 0.5)
        maximum_summary_tokens = triggers.get('maximum_summary_tokens', 32768)
        if 'summary_token_ratio' not in triggers:
            logger.warning("[SUMMARIZATION] summary_token_ratio missing from monitor.config. Using default value 0.5.")
        if not hasattr(config, 'MAX_TOKEN_COUNT'):
            logger.critical('[SUMMARIZATION] FATAL: config object missing MAX_TOKEN_COUNT.')
            raise RuntimeError('config missing MAX_TOKEN_COUNT')
        max_token_count_raw = getattr(config, "MAX_TOKEN_COUNT", None)
        if max_token_count_raw is None:
            raise RuntimeError("config missing MAX_TOKEN_COUNT")
        max_token_count = int(max_token_count_raw)
        max_summary_tokens = int(max_token_count * token_reduction_factor * summary_token_ratio)
        if max_summary_tokens > maximum_summary_tokens:
            max_summary_tokens = maximum_summary_tokens

        # Pass the summary cap using the wrapper's supported parameter name.
        # ``call_litellm_completion`` translates provider differences further
        # down the stack, but callers of ``completion_func`` may be thin
        # adapters or tests with a narrower signature, so sending
        # ``max_tokens`` here can raise unexpectedly before LiteLLM sees it.
        response = completion_func(
            model=model_name,
            messages=[
                {"role": "system", "content": f"{system_prompt}"},
                {"role": "user", "content": summarization_config['prompt']['template'].format(messages=str(messages))},
            ],
            max_completion_tokens=max_summary_tokens,
            drop_params=True
        )
        if hasattr(response, "usage") and hasattr(response.usage, "total_tokens"):
            actual_total_tokens = response.usage.total_tokens
            if hasattr(rate_limiter_obj, "add_request"):
                rate_limiter_obj.add_request(actual_total_tokens)
            logger.info(f"[SUMMARIZATION] LLM returned: usage.total_tokens={actual_total_tokens}")
        else:
            if hasattr(rate_limiter_obj, "add_request"):
                rate_limiter_obj.add_request(estimated_tokens)
            logger.warning(
                "[SUMMARIZATION] No usage.total_tokens info from LLM; only using estimated tokens for tracking."
            )
        # Post-call validation: if the actual completion size exceeds the cap
        # by more than 10%, the provider likely ignored both parameter names
        # (or accepted a different one entirely). Log loudly so the operator
        # knows the upstream cap was not enforced — the downstream truncation
        # in reset_conversation_with_summary handles the recovery, but the
        # observability is valuable for diagnosing model/provider mismatches.
        actual_completion_tokens = None
        if hasattr(response, "usage"):
            actual_completion_tokens = getattr(response.usage, "completion_tokens", None)
            if actual_completion_tokens is None:
                actual_completion_tokens = getattr(response.usage, "output_tokens", None)
        if actual_completion_tokens is not None and max_summary_tokens > 0:
            try:
                if int(actual_completion_tokens) > int(max_summary_tokens * 1.1):
                    logger.warning(
                        f"[SUMMARIZATION] Summary output cap may have been dropped by the provider: "
                        f"requested max={max_summary_tokens}, actual completion_tokens={actual_completion_tokens}. "
                        f"Downstream truncation in reset_conversation_with_summary will recover if the result exceeds budget."
                    )
            except (TypeError, ValueError):
                pass
        summary_content = None
        summary_token_count = None
        if hasattr(response, "choices") and len(response.choices) > 0 and hasattr(response.choices[0], "message"):
            summary_content = _extract_choice_message_content(response.choices[0].message)
            summary_token_count = count_message_tokens_func({"role": "system", "content": summary_content})
            logger.info(
                f"[SUMMARIZATION] Summary length: {len(summary_content)} chars, estimated {summary_token_count} tokens. Snippet: '{summary_content[:200]}...'"
            )
            log_negative_token_count(logger, config)
            if summary_token_count > summarization_config['triggers']['token_threshold'] * max_token_count:
                logger.warning(
                    f"[SUMMARIZATION] WARNING: Generated summary by itself exceeds threshold ({summary_token_count} tokens)."
                )
            if summary_token_count < 0:
                logger.critical(f"[SUMMARIZATION] CRITICAL: Negative token count for summary ({summary_token_count})!")
        else:
            logger.warning("[SUMMARIZATION] WARNING: LLM response did not include a summary message.")
        return response
    except Exception as e:
        logger.error(f"[SUMMARIZATION] Error during litellm completion: {str(e)}", exc_info=True)
        logger.critical("[SUMMARIZATION] Summarization generation failed; conversation will continue unsummarized.")
        raise

def _build_truncated_history_copy(
    conversation_history: list,
    config: HistoryConfig,
    logger: HistoryLogger,
) -> list:
    """Return a *copy* of conversation_history truncated to fit roughly half
    the model's input budget, suitable for passing to the summarizer when the
    full history exceeds what the provider will accept.

    Crucially, this does NOT mutate ``conversation_history``. The previous
    behavior truncated ``conversation_history`` in place *before* the summary
    LLM call, which meant the summarizer never saw the dropped older content
    (so the summary was a summary of only the recent tail), and any failure
    in the summary call left the conversation history irrecoverably truncated.
    The new flow passes a copy here only as a fallback when the full-history
    summarization call fails.
    """
    model_window_raw = getattr(config, "MODEL_CONTEXT_WINDOW", None)
    if model_window_raw is None:
        model_window_raw = getattr(config, "MAX_TOKEN_COUNT", None)
    model_window = model_window_raw
    try:
        if model_window is None:
            raise TypeError("model window missing")
        model_window_val = int(model_window)
    except Exception:
        fallback_window = getattr(config, "MAX_TOKEN_COUNT", 0)
        if fallback_window is None:
            fallback_window = 0
        model_window_val = int(fallback_window or 0)
    threshold = int(model_window_val / 2)
    if threshold <= 0:
        # Cannot compute a reasonable threshold; return a full-history copy.
        # The caller's second LLM attempt will either succeed or fail loudly.
        logger.warning(
            "[SUMMARIZATION] Cannot compute truncation threshold for fallback "
            "summarization; returning full-history copy."
        )
        return list(conversation_history)

    system_message = next(
        (msg for msg in conversation_history if isinstance(msg, dict) and msg.get('role') == 'system'),
        None,
    )
    kept: list = []
    kept_token_sum = 0
    for msg in reversed(conversation_history):
        if system_message is not None and msg is system_message:
            continue
        try:
            msg_tokens = count_message_tokens(msg)
        except Exception:
            logger.warning(
                "[SUMMARIZATION] Failed to count tokens for a message during "
                "fallback truncation; skipping that message."
            )
            continue
        if kept_token_sum + msg_tokens > threshold:
            break
        kept.insert(0, msg)
        kept_token_sum += msg_tokens

    truncated: list = []
    if system_message:
        truncated.append(system_message)
    truncated.extend(kept)
    return truncated


def _truncate_summary_to_fit(
    summary: str,
    system_prompt: str,
    user_input: str,
    max_tokens: int,
    model,
    logger: HistoryLogger,
) -> "str | None":
    """Return a version of ``summary`` that fits within ``max_tokens`` when combined with
    the system prompt and user input, or ``None`` when even an empty summary cannot fit.

    Uses the canonical token-counting helper to estimate the per-message budget left
    after the system prompt and user input claim their share, reserves a small safety
    margin for message-framing overhead, and delegates the actual truncation to
    ``monitor.lib.llm_usage_utils.truncate_to_token_limit`` (which uses tiktoken when available
    and a character-based fallback otherwise). The helper is imported locally to avoid
    a circular import at module load.
    """
    # Local import to avoid a circular import (llm_utils imports from history at
    # module scope).
    try:
        from monitor.lib.llm_usage_utils import truncate_to_token_limit
    except Exception as e:
        logger.error(
            f"[SUMMARIZATION] Could not import truncate_to_token_limit: {e}",
            exc_info=True,
        )
        return None

    framing_safety_margin = 32  # buffer for provider-side message framing tokens
    try:
        system_tokens = count_message_tokens({"role": "system", "content": f"{system_prompt}"})
        user_tokens = count_message_tokens({"role": "user", "content": user_input})
    except Exception as e:
        logger.error(
            f"[SUMMARIZATION] Could not count tokens for system/user messages: {e}",
            exc_info=True,
        )
        return None

    available_for_summary = max_tokens - system_tokens - user_tokens - framing_safety_margin
    if available_for_summary <= 0:
        return None

    try:
        return truncate_to_token_limit(summary, available_for_summary, model=model)
    except Exception as e:
        logger.error(
            f"[SUMMARIZATION] Truncation helper failed: {e}",
            exc_info=True,
        )
        return None


def reset_conversation_with_summary(
    summary: str,  # Fixed: expect str (content), not object
    system_prompt: str,
    user_input: str,
    conversation_history: list,
    append_func: Callable,
    logger: HistoryLogger,
    config: HistoryConfig,
) -> None:
    """
    After a summary is created, clear old conversation and set new state of [system, summary, latest user input].

    All appending and token count management routed via canonical count_message_tokens and update_token_usage from monitor.lib/token_management.py.

    When the proposed post-reset state would exceed ``config.MAX_TOKEN_COUNT``, the
    function auto-truncates the summary so the conversation can recover automatically
    instead of leaving the caller in a state that the LLM provider rejects with a
    400 "context length exceeded" on the next request. If even an empty summary plus
    the system prompt and user input cannot fit, the reset is aborted and the existing
    history is preserved.

    Args:
        summary (str): The generated summary content.
        system_prompt (str): The preserved system prompt string.
        user_input (str): The latest user input that triggered the reset.
        conversation_history (list): Mutated in-place to just system, summary, user prompt.
        append_func (Callable): For tracking tokens & appending messages. Preserved
            in the signature for backward-compatible callers but no longer used —
            the new flow performs an atomic clear-and-extend after pre-validation.
        logger (object): Logging for diagnostics.
        config (object): The live config object (will update TOTAL_TOKEN_COUNT).
    """
    # Build the proposed new history in a separate list so we can pre-validate
    # before any destructive mutation of conversation_history. Combined fix
    # for two prior bugs:
    #
    #   (a) Token-overflow at reset time was only soft-warned at 80% of
    #       MAX_TOKEN_COUNT; a summary that ended up over 100% silently produced
    #       a post-reset history that didn't fit the model, with the next turn
    #       hitting a context-window error.
    #
    #   (b) The previous flow cleared conversation_history before any append,
    #       wrapped each append in a swallowing try/except, and the underlying
    #       append_to_history_with_count also swallows exceptions internally.
    #       If any of the three appends failed at either layer, history was
    #       left in a partial state (e.g., [system] only) with the old history
    #       irrecoverable.
    #
    # New shape: build new_messages, count tokens, validate against
    # MAX_TOKEN_COUNT, then atomically clear-and-extend only on success.
    # On any failure path before the swap, conversation_history is left
    # untouched. ``append_func`` is preserved in the signature for
    # backward-compatible callers but is no longer used because the atomic
    # swap is more important than per-message callback fanout.
    del append_func

    new_messages = [
        {"role": "system", "content": f"{system_prompt}"},
        {"role": "assistant", "content": summary},
        {"role": "user", "content": user_input},
    ]
    try:
        proposed_total_tokens = count_message_tokens(new_messages)
    except Exception as e:
        logger.error(
            f"[SUMMARIZATION] Could not count tokens for proposed post-reset "
            f"history; aborting reset without modifying conversation: {e}",
            exc_info=True,
        )
        return

    max_tokens = getattr(config, "MAX_TOKEN_COUNT", None)
    truncation_applied = False
    if isinstance(max_tokens, int) and max_tokens > 0 and proposed_total_tokens > max_tokens:
        # Auto-recover: truncate the summary so it fits, rather than aborting and
        # leaving the caller with an over-budget conversation that the provider
        # rejects with 400 "context length exceeded" on the next request.
        truncated_summary = _truncate_summary_to_fit(
            summary=summary,
            system_prompt=system_prompt,
            user_input=user_input,
            max_tokens=max_tokens,
            model=getattr(config, "MODEL", None),
            logger=logger,
        )
        if truncated_summary is None:
            logger.critical(
                f"[SUMMARIZATION] Cannot fit post-reset history within MAX_TOKEN_COUNT "
                f"({max_tokens}); even an empty summary plus system prompt and user "
                f"input would exceed the budget. Aborting reset to preserve existing history."
            )
            return
        new_messages = [
            {"role": "system", "content": f"{system_prompt}"},
            {"role": "assistant", "content": truncated_summary},
            {"role": "user", "content": user_input},
        ]
        try:
            proposed_total_tokens = count_message_tokens(new_messages)
        except Exception as e:
            logger.error(
                f"[SUMMARIZATION] Could not count tokens for truncated post-reset history; "
                f"aborting reset without modifying conversation: {e}",
                exc_info=True,
            )
            return
        if proposed_total_tokens > max_tokens:
            # Defensive: truncation helper produced something still too large.
            logger.critical(
                f"[SUMMARIZATION] Truncated summary still exceeds MAX_TOKEN_COUNT "
                f"({proposed_total_tokens} > {max_tokens}). Aborting reset to "
                f"preserve existing history."
            )
            return
        truncation_applied = True
        logger.warning(
            f"[SUMMARIZATION] Summary was too large to fit; truncated to recover. "
            f"Post-reset state: {proposed_total_tokens}/{max_tokens} tokens."
        )

    # Validation passed — perform the atomic swap.
    prev_total_tokens = getattr(config, "TOTAL_TOKEN_COUNT", None)
    conversation_history.clear()
    conversation_history.extend(new_messages)
    logger.debug(f"[RESET_CONVERSATION] Atomically swapped conversation history for summary reset.")

    if hasattr(config, "TOTAL_TOKEN_COUNT"):
        logger.info(
            f"[SUMMARIZATION] Updating config.TOTAL_TOKEN_COUNT: "
            f"old value={prev_total_tokens}, new value={proposed_total_tokens}"
        )
        config.TOTAL_TOKEN_COUNT = proposed_total_tokens
    else:
        logger.warning(
            f"[SUMMARIZATION] config object has no TOTAL_TOKEN_COUNT attribute"
            f"—cannot update token count after reset."
        )
    log_negative_token_count(logger, config)
    if isinstance(max_tokens, int) and max_tokens > 0 and proposed_total_tokens > 0.8 * max_tokens:
        logger.warning(
            f"[SUMMARIZATION] Warning: Even after summary, tokens in conversation"
            f" are close to the allowable maximum ({proposed_total_tokens})."
        )
    if proposed_total_tokens < 0:
        logger.critical("[SUMMARIZATION] CRITICAL: Negative total token count detected after reset!")
    logger.info(
        f"[SUMMARIZATION] Conversation reset after summary. New state: "
        f"{len(conversation_history)} messages, total tokens: {proposed_total_tokens}"
    )

def _find_compaction_split_index(history, recent_turns_k):
    """Find the index in ``history`` at which to start preserving messages
    verbatim during partial-preserve compaction. Everything BEFORE this
    index gets summarized; everything FROM the index onward stays as-is.

    A "turn" begins at a user message and ends at the next user message
    (or end-of-history). To preserve the last ``recent_turns_k`` turns,
    the split point is the index of the k-th-to-last user message.

    The returned index is always a user-message boundary, which keeps
    tool_call/tool_result chains intact: a chain is bounded by user
    messages on both ends, so splitting at a user-message index never
    lands in the middle of a chain.

    Args:
        history: The conversation history list (list of message dicts).
        recent_turns_k: How many recent turns to preserve verbatim.

    Returns:
        int: Index of the split point (inclusive — preserve from this index).
        None: When compaction should be skipped — either history is empty,
            recent_turns_k <= 0, or there aren't more user messages than
            recent_turns_k (nothing old enough to summarize).
    """
    if not history or recent_turns_k <= 0:
        return None

    user_indices = [i for i, m in enumerate(history) if isinstance(m, dict) and m.get("role") == "user"]

    # Need strictly more user messages than K — otherwise everything is
    # already "recent" and there is no old portion to summarize.
    if len(user_indices) <= recent_turns_k:
        return None

    return user_indices[-recent_turns_k]


def reset_conversation_with_partial_summary(
    summary: str,
    system_prompt: str,
    preserved_messages: list,
    conversation_history: list,
    logger: HistoryLogger,
    config: HistoryConfig,
) -> None:
    """Partial-preserve sibling of ``reset_conversation_with_summary``.

    Builds the post-compaction history as::

        [{system_prompt}, {assistant: summary}, *preserved_messages]

    and atomically swaps it into ``conversation_history``. Uses the same
    overflow-handling pattern as the full-reset variant: if the proposed
    state exceeds ``config.MAX_TOKEN_COUNT``, the summary is truncated; if
    even truncation can't fit, the reset is aborted and ``conversation_history``
    is left untouched.

    The caller is responsible for choosing ``preserved_messages`` so that
    the resulting message sequence is valid (tool_call/tool_result pairing,
    etc.) — see ``_find_compaction_split_index`` which guarantees a
    user-message boundary.

    Args:
        summary: Generated summary text for the older portion of history.
        system_prompt: Preserved system prompt string.
        preserved_messages: Recent messages to keep verbatim — must start
            at a user message and contain at least one entry.
        conversation_history: Mutated in-place via atomic clear+extend on
            successful validation.
        logger: For diagnostics.
        config: Live config object — read ``MAX_TOKEN_COUNT`` and update
            ``TOTAL_TOKEN_COUNT`` post-swap.
    """
    if not preserved_messages:
        logger.warning(
            "[SUMMARIZATION] reset_conversation_with_partial_summary called with empty "
            "preserved_messages; aborting to avoid wiping history. Caller should have "
            "checked _find_compaction_split_index for None and skipped compaction."
        )
        return

    new_messages = [
        {"role": "system", "content": f"{system_prompt}"},
        {"role": "assistant", "content": summary},
        *preserved_messages,
    ]

    try:
        proposed_total_tokens = count_message_tokens(new_messages)
    except Exception as e:
        logger.error(
            f"[SUMMARIZATION] Could not count tokens for proposed partial-reset history; "
            f"aborting without modifying conversation: {e}",
            exc_info=True,
        )
        return

    max_tokens = getattr(config, "MAX_TOKEN_COUNT", None)
    truncation_applied = False
    if isinstance(max_tokens, int) and max_tokens > 0 and proposed_total_tokens > max_tokens:
        # The preserved-messages portion is fixed (we can't drop turns the user
        # cares about); the summary is the only knob to turn. Use the same
        # truncation helper the full-reset path uses, but pass a synthesized
        # user_input string that captures the token weight of the preserved
        # portion so the helper budgets correctly.
        try:
            preserved_tokens = count_message_tokens(preserved_messages)
        except Exception as e:
            logger.error(
                f"[SUMMARIZATION] Could not count tokens for preserved messages during "
                f"partial-reset truncation; aborting: {e}",
                exc_info=True,
            )
            return

        # Available budget for the summary itself, conservatively. Reserve
        # tokens for system_prompt + preserved + a small overhead margin.
        try:
            system_tokens = count_message_tokens([{"role": "system", "content": system_prompt}])
        except Exception:
            system_tokens = 0
        overhead_margin = 64
        budget_for_summary = max_tokens - system_tokens - preserved_tokens - overhead_margin

        if budget_for_summary <= 0:
            logger.critical(
                f"[SUMMARIZATION] Cannot fit partial-reset history within MAX_TOKEN_COUNT "
                f"({max_tokens}): preserved messages ({preserved_tokens}) plus system prompt "
                f"({system_tokens}) already exceed the budget. Aborting reset to preserve "
                f"existing history."
            )
            return

        # Truncate by character ratio — same approximate-tokens-per-char heuristic
        # used elsewhere in this module. We over-shoot the budget by undershooting
        # the summary length, then re-validate below.
        approx_chars_per_token = 4
        target_chars = max(0, budget_for_summary * approx_chars_per_token)
        truncated_summary = summary[:target_chars]
        new_messages = [
            {"role": "system", "content": f"{system_prompt}"},
            {"role": "assistant", "content": truncated_summary},
            *preserved_messages,
        ]
        try:
            proposed_total_tokens = count_message_tokens(new_messages)
        except Exception as e:
            logger.error(
                f"[SUMMARIZATION] Could not count tokens for truncated partial-reset history; "
                f"aborting: {e}",
                exc_info=True,
            )
            return

        if proposed_total_tokens > max_tokens:
            logger.critical(
                f"[SUMMARIZATION] Truncated partial-reset state still exceeds MAX_TOKEN_COUNT "
                f"({proposed_total_tokens} > {max_tokens}). Aborting reset to preserve "
                f"existing history."
            )
            return

        truncation_applied = True
        logger.warning(
            f"[SUMMARIZATION] Summary was too large to fit; truncated to recover. "
            f"Partial-reset state: {proposed_total_tokens}/{max_tokens} tokens."
        )

    # Validation passed — atomic swap.
    prev_total_tokens = getattr(config, "TOTAL_TOKEN_COUNT", None)
    conversation_history.clear()
    conversation_history.extend(new_messages)

    if hasattr(config, "TOTAL_TOKEN_COUNT"):
        logger.info(
            f"[SUMMARIZATION] Partial-reset complete (preserved {len(preserved_messages)} "
            f"recent messages). Updating TOTAL_TOKEN_COUNT: old={prev_total_tokens}, "
            f"new={proposed_total_tokens}, truncated_summary={truncation_applied}."
        )
        config.TOTAL_TOKEN_COUNT = proposed_total_tokens

    log_negative_token_count(logger, config)


# --- Tool-body demotion ------------------------------------------------------
#
# Once a tool result or bulky tool-call argument has aged past a few user
# turns, the model rarely needs the raw bytes again. We rewrite those
# bulky payloads in-place into short sentinel-marked placeholders so the
# prompt cost drops on every subsequent turn. The sentinel acts as the
# idempotency marker — already-demoted messages are skipped on later
# passes, so the cached prompt prefix stabilizes after one transition
# rather than churning every turn.

DEMOTION_SENTINEL = "[demoted-tool-body]"
MIN_BODY_SIZE_TO_DEMOTE = 200  # chars — below this, the savings aren't worth the placeholder noise


def _is_already_demoted(content):
    """Return True if ``content`` carries the demotion sentinel — used as
    the idempotency marker so we don't rewrite the same message every turn."""
    return isinstance(content, str) and content.startswith(DEMOTION_SENTINEL)


def _demote_tool_result_content(msg):
    """In-place demotion of a tool-role message's ``content``. Returns True
    if the message was rewritten, False otherwise (already demoted, too
    short, or content not a string)."""
    content = msg.get("content")
    if not isinstance(content, str):
        return False
    if _is_already_demoted(content):
        return False
    if len(content) < MIN_BODY_SIZE_TO_DEMOTE:
        return False
    original_size = len(content)
    msg["content"] = (
        f"{DEMOTION_SENTINEL} {original_size} chars from this tool result "
        "were omitted to save context. Re-call the tool if you need the content again."
    )
    return True


def _demote_assistant_tool_call_arguments(msg):
    """In-place demotion of any bulky string values inside the ``tool_calls``
    array on an assistant-role message. The ``function.arguments`` JSON
    string is parsed, large string fields are replaced with short placeholders,
    and the JSON is re-serialized. Returns True if anything was rewritten."""
    tool_calls = msg.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return False

    any_changed = False
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function")
        if not isinstance(fn, dict):
            continue
        args_str = fn.get("arguments")
        if not isinstance(args_str, str):
            continue
        if _is_already_demoted(args_str):
            continue
        if len(args_str) < MIN_BODY_SIZE_TO_DEMOTE:
            continue

        try:
            parsed = json.loads(args_str)
        except (json.JSONDecodeError, ValueError):
            # Malformed JSON — leave it alone so we don't silently corrupt
            # the message. The model already sees garbage; we don't add to it.
            continue
        if not isinstance(parsed, dict):
            continue

        modified = False
        for key, value in list(parsed.items()):
            if isinstance(value, str) and len(value) >= MIN_BODY_SIZE_TO_DEMOTE:
                parsed[key] = f"[demoted: {len(value)} chars omitted from `{key}`]"
                modified = True

        if modified:
            try:
                fn["arguments"] = json.dumps(parsed)
                any_changed = True
            except (TypeError, ValueError):
                # Re-serialization failed somehow (shouldn't happen with dict
                # of str/numbers, but defensively): leave the original args
                # in place rather than risk producing invalid JSON.
                continue

    return any_changed


def demote_old_tool_bodies(history, turns_threshold):
    """Walk ``history`` and demote bulky tool-related content in messages
    older than the last ``turns_threshold`` user-message-bounded turns.
    Operates in-place. Returns the number of messages rewritten this pass.

    "Older" is defined by the same user-message-boundary scheme used by
    ``_find_compaction_split_index``: the boundary is the index of the
    turns_threshold-th-to-last user message; everything before that index
    is fair game for demotion.

    Idempotency: each rewritten message gets a sentinel prefix on its
    content, and subsequent passes skip already-marked messages. This
    means the cached prompt prefix stabilizes after a one-time transition
    when a message crosses the boundary — not on every turn.

    Args:
        history: The conversation history list. Mutated in place.
        turns_threshold: How many recent user turns to leave untouched.

    Returns:
        int: Count of messages that were rewritten this pass.
    """
    if not history or turns_threshold <= 0:
        return 0

    user_indices = [
        i for i, m in enumerate(history)
        if isinstance(m, dict) and m.get("role") == "user"
    ]

    # If there aren't more user messages than the threshold, nothing has
    # aged past the boundary yet.
    if len(user_indices) <= turns_threshold:
        return 0

    boundary = user_indices[-turns_threshold]

    demoted_count = 0
    for i in range(boundary):
        msg = history[i]
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "tool":
            if _demote_tool_result_content(msg):
                demoted_count += 1
        elif role == "assistant":
            if _demote_assistant_tool_call_arguments(msg):
                demoted_count += 1

    return demoted_count


# End of history.py
