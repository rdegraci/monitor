import logging
import litellm
import monitor.lib.llm_utils as llm_utils
import signal
import threading
import uuid

logger = logging.getLogger(__name__)

from monitor.core.tooling import handle_tool_call, handle
from monitor.core.tools import TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS
from monitor.lib import rate_limiter

from monitor.lib.message_utils import (
    prepare_messages_with_cache_control,
    normalize_message,
    sanitize_messages,
)
from monitor.lib.preferences import PREFERENCE_PROMPT
from monitor.lib.history import (
    append_to_history_with_count,
    _find_compaction_split_index,
    generate_conversation_summary,
    reset_conversation_with_partial_summary,
    reset_conversation_with_summary,
)
from monitor.lib.token_management import (
    count_message_tokens,
    update_token_usage,
    token_budgeter,
)
from monitor.lib.system_prompt import build_system_prompt
from monitor.lib.progress import progress_dots

from monitor.lib.llm_utils import (
    dict_to_attr,
    validate_tool_message_order,
    determine_response_type,
    process_direct_response,
    extract_tool_calls,
    process_response_by_finish_reason,
    call_litellm_completion,
    AttrDict,
    is_reasoning_model,
)

# Import responses API adapter
from monitor.core.llm_responses_adapter import (
    response_completion,
    get_response_initial_completion,
)


def _cfg():
    """Return the late-bound config from llm_utils.

    Returns:
        Any: The config object attached to monitor.lib.llm_utils.
    """
    return llm_utils.config


def should_use_responses_adapter():
    """Determine whether to use the Responses adapter.

    This gating helper ensures the Responses API is only used when:
      - RESPONSES_API is True
      - REASONING_MODEL_PREFIX is a non-empty string
      - MODEL is a string and starts with REASONING_MODEL_PREFIX (case-insensitive)

    Returns:
        bool: True if the Responses adapter should be used; False otherwise.

    Exceptions:
        Any exceptions are caught; the error is logged at debug level and False is returned.
    """
    try:
        if getattr(_cfg(), "RESPONSES_API", None) is not True:
            return False
        prefix = getattr(_cfg(), "REASONING_MODEL_PREFIX", None)
        if not isinstance(prefix, str) or prefix == "":
            return False
        model = getattr(_cfg(), "MODEL", None)
        if not isinstance(model, str):
            return False
        return is_reasoning_model(model, prefix)
    except Exception as e:
        logger.error(f"should_use_responses_adapter check failed: {e}", exc_info=True)
        return False


def extract_user_input_from_history():
    """Extract the most recent user input from conversation history.

    This is used by responses API which needs the current user query
    rather than full conversation context.

    Returns:
        str: The most recent user input, or empty string if not found
    """
    try:
        history = getattr(_cfg(), "CONVERSATION_HISTORY", []) or []
        if not isinstance(history, list):
            history = []
        # Look for the most recent user message in conversation history
        for message in reversed(history):
            if isinstance(message, dict) and message.get("role") == "user":
                return message.get("content", "")

        logger.warning("No user input found in conversation history")
        return ""

    except Exception as e:
        logger.error(f"Error extracting user input from history: {e}", exc_info=True)
        return ""


def _apply_tool_output_budgeting(messages, input_window_limit):
    """Apply token budgeting to tool output messages and re-estimate request size.

    Extracts tool output strings from the messages, budgets them using the configured
    token_budgeter to fit within the given input window, maps the trimmed outputs back
    to the corresponding tool messages, then recomputes token estimates and validates
    message order.

    Args:
        messages (list[dict]): Conversation messages to mutate in place.
        input_window_limit (int): The input window limit used for budgeting.

    Returns:
        tuple[int, int, str|None]:
            - estimated_tokens: Recomputed total input tokens after budgeting.
            - estimated_request: Input tokens plus potential reasoning completion allowance.
            - error_message: Validation error message if any; otherwise None.
    """
    try:
        tool_outputs = [
            m.get("content")
            for m in messages
            if m.get("role") == "tool" and isinstance(m.get("content"), str)
        ]
        params = {"input": [{"output": c} for c in tool_outputs]}
        if params["input"]:
            budgeted = token_budgeter(
                params,
                input_window=input_window_limit,
                model_name=_cfg().MODEL,
            )
            # Map any trimmed outputs back to corresponding tool messages (preserve order)
            idx = 0
            budgeted_list = (
                budgeted.get("input", []) if isinstance(budgeted, dict) else []
            )
            for m in messages:
                if m.get("role") == "tool" and isinstance(m.get("content"), str):
                    if idx < len(budgeted_list):
                        new_output = budgeted_list[idx].get("output", m.get("content"))
                        if isinstance(new_output, str):
                            m["content"] = new_output
                    idx += 1

        # Recompute estimated tokens and request after trimming and re-validate
        estimated_tokens = 0
        for msg in messages:
            normalized_msg = normalize_message(msg)
            estimated_tokens += count_message_tokens(normalized_msg)

        reasoning_allowance = (
            getattr(_cfg(), "REASONING_MAX_COMPLETION_TOKENS", 0)
            if is_reasoning_model(
                getattr(_cfg(), "MODEL", None),
                getattr(_cfg(), "REASONING_MODEL_PREFIX", None),
            )
            else 0
        )
        estimated_request = estimated_tokens + (reasoning_allowance or 0)

        try:
            validate_tool_message_order(messages)
        except ValueError as ve:
            logger.error(f"Message validation failed after token budgeting: {ve}", exc_info=True)
            return (
                estimated_tokens,
                estimated_request,
                "There was an issue with tool message ordering after reducing output. Please try your request again.",
            )

        return estimated_tokens, estimated_request, None
    except Exception as be:
        logger.error(f"Token budgeting failed: {be}", exc_info=True)
        # Fall back to computing estimates without changes
        estimated_tokens = 0
        for i, msg in enumerate(messages):
            try:
                normalized_msg = normalize_message(msg)
                estimated_tokens += count_message_tokens(normalized_msg)
            except Exception:
                logger.warning(f"Using default token estimate (100) for message at index {i} due to normalization/counting failure")
                estimated_tokens += 100
        reasoning_allowance = (
            getattr(_cfg(), "REASONING_MAX_COMPLETION_TOKENS", 0)
            if is_reasoning_model(
                getattr(_cfg(), "MODEL", None),
                getattr(_cfg(), "REASONING_MODEL_PREFIX", None),
            )
            else 0
        )
        estimated_request = estimated_tokens + (reasoning_allowance or 0)
        return estimated_tokens, estimated_request, f"Token budgeting failed: {be}"


def cancellable_call_litellm_completion(model, messages, tool_descriptions, gemini_tool_descriptions):
    """Run the blocking LLM completion in a background thread and allow Ctrl-C to cancel waiting.

    Behavior:
      - Temporarily sets SIGINT handler to the default to raise KeyboardInterrupt on Ctrl-C.
      - Starts the LLM call in a daemon background thread.
      - Displays a progress indicator while waiting.
      - Polls the thread with short timeouts, so KeyboardInterrupt can be handled promptly.
      - If interrupted, stops waiting and returns (None, True).
      - On success, returns (response, False).
      - Any exception from the background call is re-raised here.

    Args:
        model (str): Model name to pass to the completion call.
        messages (list[dict]): Messages payload.
        tool_descriptions (Any): Tool descriptions to pass through.
        gemini_tool_descriptions (Any): Gemini tool descriptions to pass through.

    Returns:
        tuple[Any|None, bool]: (response, was_cancelled)
    """
    prev_sigint = None
    # Container to communicate results/exceptions from background thread
    result = {"response": None, "exception": None}

    def target():
        try:
            result["response"] = call_litellm_completion(
                model, messages, tool_descriptions, gemini_tool_descriptions
            )
        except Exception as e:
            result["exception"] = e

    t = threading.Thread(target=target, daemon=True)

    with progress_dots():
        try:
            # Ensure Ctrl-C raises KeyboardInterrupt in this scope
            prev_sigint = signal.getsignal(signal.SIGINT)
            try:
                signal.signal(signal.SIGINT, signal.default_int_handler)
            except Exception:
                # If setting signal handler fails (e.g., non-main thread environment), continue safely
                prev_sigint = None
            t.start()
            while t.is_alive():
                t.join(timeout=0.1)
        except KeyboardInterrupt:
            # Cancel waiting and return control to caller
            return None, True
        finally:
            # Restore previous SIGINT handler if we changed it
            if prev_sigint is not None:
                try:
                    signal.signal(signal.SIGINT, prev_sigint)
                except Exception:
                    pass

    if result["exception"] is not None:
        # Propagate exception to existing error handling logic
        raise result["exception"]

    return result["response"], False


def get_llm_completion(log_prefix="", error_message="Error during litellm completion"):
    """Common logic for getting completion from LLM with error handling and rate limiting.
    Token counting and updates use canonical helpers from monitor.lib/token_management.py.

    Adapter gating is performed via should_use_responses_adapter(), which returns True only when:
      - RESPONSES_API is True
      - REASONING_MODEL_PREFIX is a non-empty string
      - MODEL is a string that starts with REASONING_MODEL_PREFIX

    If the adapter is not used, falls back to the conversations API.

    This call is cancellable: pressing Ctrl-C while waiting for the model response will
    cancel the wait, stop the progress indicator, and return (None, "Cancelled by user").
    """
    # Check if responses API should be used
    if should_use_responses_adapter():
        logger.debug("Using responses API for completion")
        user_input = extract_user_input_from_history()
        if not user_input:
            return None, "No user input found in conversation history for responses API"

        return response_completion(
            user_input=user_input,
            tool_descriptions=TOOL_DESCRIPTIONS,
            gemini_tool_descriptions=GEMINI_TOOL_DESCRIPTIONS,
            log_prefix=log_prefix,
            error_message=error_message,
        )

    # Use conversations API (existing logic)
    logger.debug("Using conversations API for completion")
    try:
        summarization_attempted = False
        # Build conversation messages
        messages = prepare_messages_with_cache_control(
            _cfg().CONVERSATION_HISTORY, _cfg().MODEL
        )
        preferences = getattr(_cfg(), "PREFERENCE_PROMPT", PREFERENCE_PROMPT)
        if preferences:
            # Prepend user preferences as a system message (always check latest state)
            messages = [{"role": "system", "content": preferences}] + messages

        # Sanitize messages before counting, validation, and sending
        messages = sanitize_messages(messages)

        # Determine input window limit (prefer MODEL_INPUT_WINDOW, then MODEL_CONTEXT_WINDOW)
        input_window_limit = None
        try:
            iw = getattr(_cfg(), "MODEL_INPUT_WINDOW", None)
            cw = getattr(_cfg(), "MODEL_CONTEXT_WINDOW", None)
            input_window_limit = (
                iw
                if isinstance(iw, int) and iw > 0
                else (cw if isinstance(cw, int) and cw > 0 else None)
            )
        except Exception:
            input_window_limit = None

        # Log if input window gating is disabled
        if input_window_limit is None:
            logger.debug(
                "Input size gating is disabled: no valid MODEL_INPUT_WINDOW or MODEL_CONTEXT_WINDOW configured"
            )

        # Estimate token count for the conversation history using canonical helper
        estimated_tokens = 0
        for msg in messages:
            normalized_msg = normalize_message(msg)
            estimated_tokens += count_message_tokens(normalized_msg)

        # Preflight validation before rate limiting and request sizing
        try:
            validate_tool_message_order(messages)
        except ValueError as ve:
            logger.error(f"Message validation failed (pre-wait): {ve}")
            return None, str(ve)

        reasoning_allowance = (
            getattr(_cfg(), "REASONING_MAX_COMPLETION_TOKENS", 0)
            if is_reasoning_model(_cfg().MODEL, getattr(_cfg(), "REASONING_MODEL_PREFIX", None))
            else 0
        )
        estimated_request = estimated_tokens + (reasoning_allowance or 0)

        # Early token budgeting for tool outputs before auto-summarization
        if input_window_limit is not None and estimated_tokens > input_window_limit:
            try:
                new_tokens, new_request, err = _apply_tool_output_budgeting(
                    messages, input_window_limit
                )
                estimated_tokens = new_tokens
                estimated_request = new_request
                if err:
                    return None, err
            except Exception as be:
                logger.error(f"Early token budgeting failed: {be}", exc_info=True)

        # Input/window-size gating and auto-summarization. Trigger fires at the
        # SOFT threshold (config.AUTO_COMPACT_THRESHOLD_RATIO × input_window) so
        # compaction runs proactively, well before the hard ceiling. The hard
        # ceiling at the `return None, ...` check below remains as a backstop
        # for cases where compaction can't bring the prompt under (e.g. a
        # single huge tool result).
        _compact_ratio = getattr(_cfg(), "AUTO_COMPACT_THRESHOLD_RATIO", 0.30)
        _soft_threshold = (
            int(input_window_limit * _compact_ratio)
            if input_window_limit is not None
            else None
        )
        if _soft_threshold is not None and estimated_tokens > _soft_threshold:
            if (
                getattr(_cfg(), "ENABLE_AUTO_SUMMARIZE_ON_LIMIT", False)
                and not summarization_attempted
            ):
                logger.info(
                    "Attempting auto-summarization: prompt %d tokens exceeds soft threshold %d "
                    "(%.0f%% of %d-token input window).",
                    estimated_tokens, _soft_threshold,
                    _compact_ratio * 100, input_window_limit,
                )
                try:
                    # Partial-preserve compaction: only summarize the OLDER
                    # portion of history, keeping the last K user turns
                    # verbatim. The split index is the start of the K-th-to-last
                    # user message (None when there aren't enough turns to
                    # bother — in that case we skip compaction silently).
                    _k = getattr(_cfg(), "RECENT_TURNS_PRESERVED_ON_COMPACT", 6)
                    _split_idx = _find_compaction_split_index(_cfg().CONVERSATION_HISTORY, _k)
                    if _split_idx is None:
                        logger.info(
                            "Skipping compaction: history has <= %d user turns; nothing old "
                            "enough to summarize. Will fall through to hard-limit check.", _k,
                        )
                    else:
                        _old_portion = list(_cfg().CONVERSATION_HISTORY[:_split_idx])
                        _preserved = list(_cfg().CONVERSATION_HISTORY[_split_idx:])
                        summary_response = generate_conversation_summary(
                            build_system_prompt(session_id=getattr(_cfg(), "SESSION_ID", None)),
                            _old_portion,
                            _cfg().SUMMARIZATION_CONFIG,
                            _cfg().MODEL,
                            litellm.completion,
                            count_message_tokens,
                            rate_limiter.RATE_LIMITER,
                            logger,
                            _cfg(),
                        )
                        summary_content = None
                        try:
                            response_attr = dict_to_attr(summary_response)
                            if (
                                hasattr(response_attr, "choices")
                                and response_attr.choices
                                and len(response_attr.choices) > 0
                                and hasattr(response_attr.choices[0], "message")
                                and response_attr.choices[0].message
                                and hasattr(response_attr.choices[0].message, "content")
                            ):
                                summary_content = (
                                    response_attr.choices[0].message.content
                                )
                        except Exception:
                            pass

                        reset_conversation_with_partial_summary(
                            summary_content or "",
                            build_system_prompt(session_id=getattr(_cfg(), "SESSION_ID", None)),
                            _preserved,
                            _cfg().CONVERSATION_HISTORY,
                            logger,
                            _cfg(),
                        )
                        summarization_attempted = True

                    messages = prepare_messages_with_cache_control(
                        _cfg().CONVERSATION_HISTORY, _cfg().MODEL
                    )
                    if preferences:
                        messages = [{"role": "system", "content": preferences}] + messages
                    messages = sanitize_messages(messages)
                    estimated_tokens = 0
                    for msg in messages:
                        normalized_msg = normalize_message(msg)
                        estimated_tokens += count_message_tokens(normalized_msg)
                    # Validate again after messages are rebuilt
                    try:
                        validate_tool_message_order(messages)
                    except ValueError as ve:
                        logger.error(
                            "Message validation failed after summarization "
                            f"(token limit path): {ve}"
                        )
                        return None, str(ve)
                    reasoning_allowance = (
                        getattr(_cfg(), "REASONING_MAX_COMPLETION_TOKENS", 0)
                        if is_reasoning_model(
                            _cfg().MODEL, getattr(_cfg(), "REASONING_MODEL_PREFIX", None)
                        )
                        else 0
                    )
                    estimated_request = estimated_tokens + (reasoning_allowance or 0)

                    # Apply budgeting again after summarization before final size check
                    try:
                        new_tokens, new_request, err = _apply_tool_output_budgeting(
                            messages, input_window_limit
                        )
                        estimated_tokens = new_tokens
                        estimated_request = new_request
                        if err:
                            return None, err
                    except Exception as be:
                        logger.error(
                            f"Token budgeting failed after summarization: {be}",
                            exc_info=True,
                        )

                    logger.info("Auto-summarization complete; retrying request.")
                except Exception as se:
                    logger.error(f"Auto-summarization failed: {se}", exc_info=True)

        if input_window_limit is not None and estimated_tokens > input_window_limit:
            return None, (
                f"Input too large: {estimated_tokens} tokens "
                f"vs input window {input_window_limit}. Cannot send request. "
                "Please reduce the size of your input (file, diff, or message) or send smaller requests."
            )

        # Validate before waiting on rate limiter
        try:
            validate_tool_message_order(messages)
        except ValueError as ve:
            logger.error(f"Message validation failed (before rate limit wait): {ve}")
            return None, str(ve)

        wait_result = rate_limiter.RATE_LIMITER.wait_if_needed(estimated_request)
        if wait_result is None:
            if (
                getattr(_cfg(), "ENABLE_AUTO_SUMMARIZE_ON_LIMIT", False)
                and not summarization_attempted
            ):
                logger.info(
                    "Attempting auto-summarization due to rate limit safety threshold..."
                )
                try:
                    # Same partial-preserve compaction as the soft-trigger path.
                    _k = getattr(_cfg(), "RECENT_TURNS_PRESERVED_ON_COMPACT", 6)
                    _split_idx = _find_compaction_split_index(_cfg().CONVERSATION_HISTORY, _k)
                    if _split_idx is None:
                        logger.info(
                            "Skipping compaction (rate-limit path): history has <= %d user "
                            "turns. Will retry rate-limit wait without summarization.", _k,
                        )
                    else:
                        _old_portion = list(_cfg().CONVERSATION_HISTORY[:_split_idx])
                        _preserved = list(_cfg().CONVERSATION_HISTORY[_split_idx:])
                        summary_response = generate_conversation_summary(
                            build_system_prompt(session_id=getattr(_cfg(), "SESSION_ID", None)),
                            _old_portion,
                            _cfg().SUMMARIZATION_CONFIG,
                            _cfg().MODEL,
                            litellm.completion,
                            count_message_tokens,
                            rate_limiter.RATE_LIMITER,
                            logger,
                            _cfg(),
                        )
                        summary_content = None
                        try:
                            response_attr = dict_to_attr(summary_response)
                            if (
                                hasattr(response_attr, "choices")
                                and response_attr.choices
                                and len(response_attr.choices) > 0
                                and hasattr(response_attr.choices[0], "message")
                                and response_attr.choices[0].message
                                and hasattr(response_attr.choices[0].message, "content")
                            ):
                                summary_content = (
                                    response_attr.choices[0].message.content
                                )
                        except Exception:
                            pass

                        reset_conversation_with_partial_summary(
                            summary_content or "",
                            build_system_prompt(session_id=getattr(_cfg(), "SESSION_ID", None)),
                            _preserved,
                            _cfg().CONVERSATION_HISTORY,
                            logger,
                            _cfg(),
                        )
                        summarization_attempted = True

                    messages = prepare_messages_with_cache_control(
                        _cfg().CONVERSATION_HISTORY, _cfg().MODEL
                    )
                    if preferences:
                        messages = [{"role": "system", "content": preferences}] + messages
                    messages = sanitize_messages(messages)
                    estimated_tokens = 0
                    for msg in messages:
                        normalized_msg = normalize_message(msg)
                        estimated_tokens += count_message_tokens(normalized_msg)
                    reasoning_allowance = (
                        getattr(_cfg(), "REASONING_MAX_COMPLETION_TOKENS", 0)
                        if is_reasoning_model(
                            _cfg().MODEL, getattr(_cfg(), "REASONING_MODEL_PREFIX", None)
                        )
                        else 0
                    )
                    estimated_request = estimated_tokens + (reasoning_allowance or 0)
                    # Validate after rebuilding messages in rate limit summarization path
                    try:
                        validate_tool_message_order(messages)
                    except ValueError as ve:
                        logger.error(
                            "Message validation failed after summarization "
                            f"(rate limit path): {ve}"
                        )
                        return None, str(ve)
                    logger.info("Auto-summarization complete; retrying request.")
                except Exception as se:
                    logger.error(f"Auto-summarization failed: {se}", exc_info=True)

                # Validate before attempting the second wait
                try:
                    validate_tool_message_order(messages)
                except ValueError as ve:
                    logger.error(
                        f"Message validation failed (before second rate limit wait): {ve}"
                    )
                    return None, str(ve)

                wait_result = rate_limiter.RATE_LIMITER.wait_if_needed(
                    estimated_request
                )

            if wait_result is None:
                return None, (
                    f"Rate limit safety threshold exceeded: {estimated_request} tokens. Model TPM limit {_cfg().MODEL_MAX_TPM}. "
                    "Reduce your request size or wait before retrying."
                )

        # Apply token budgeting to tool output messages before final completion call
        if input_window_limit is not None and estimated_tokens >= int(0.9 * input_window_limit):
            try:
                tool_outputs = [
                    m.get("content")
                    for m in messages
                    if m.get("role") == "tool" and isinstance(m.get("content"), str)
                ]
                params = {"input": [{"output": c} for c in tool_outputs]}
                if params["input"]:
                    budgeted = token_budgeter(
                        params,
                        input_window=input_window_limit,
                        model_name=_cfg().MODEL,
                    )
                    # Map any trimmed outputs back to corresponding tool messages (preserve order)
                    idx = 0
                    budgeted_list = (
                        budgeted.get("input", []) if isinstance(budgeted, dict) else []
                    )
                    for m in messages:
                        if m.get("role") == "tool" and isinstance(
                            m.get("content"), str
                        ):
                            if idx < len(budgeted_list):
                                new_output = budgeted_list[idx].get(
                                    "output", m.get("content")
                                )
                                if isinstance(new_output, str):
                                    m["content"] = new_output
                            idx += 1

                    # Recompute estimated tokens and request after trimming and re-validate
                    estimated_tokens = 0
                    for msg in messages:
                        normalized_msg = normalize_message(msg)
                        estimated_tokens += count_message_tokens(normalized_msg)
                    reasoning_allowance = (
                        getattr(_cfg(), "REASONING_MAX_COMPLETION_TOKENS", 0)
                        if is_reasoning_model(
                            _cfg().MODEL, getattr(_cfg(), "REASONING_MODEL_PREFIX", None)
                        )
                        else 0
                    )
                    estimated_request = estimated_tokens + (reasoning_allowance or 0)
                    try:
                        validate_tool_message_order(messages)
                    except ValueError as ve:
                        logger.error(
                            f"Message validation failed after token budgeting: {ve}"
                        )
                        return None, str(ve)
            except Exception as be:
                logger.error(f"Token budgeting failed: {be}", exc_info=True)

        # Final validation just before making the completion call
        try:
            validate_tool_message_order(messages)
        except ValueError as ve:
            logger.error(f"Message validation failed (pre-completion): {ve}")
            return None, str(ve)

        # M-rl2: a per-request UUID is shared between the cancellation-path
        # accounting and the success-path accounting. If both fire (e.g.,
        # cancellation records an estimate, and the eventual provider response
        # is later processed and records the actual count), add_request
        # replaces the entry in place instead of double-counting.
        request_id = uuid.uuid4().hex

        response, was_cancelled = cancellable_call_litellm_completion(
            _cfg().MODEL, messages, TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS
        )
        if was_cancelled:
            try:
                update_token_usage(estimated_request, used_estimate=True)
            except Exception:
                pass
            try:
                if hasattr(rate_limiter, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
                    rate_limiter.RATE_LIMITER.add_request(estimated_request, request_id=request_id)
            except Exception:
                pass
            return None, "Cancelled by user"

        # Convert response (and possibly inner objects) to attribute-access-friendly structures
        response = dict_to_attr(response)

        # Record actual usage using canonical update
        usage_obj = getattr(response, "usage", None)
        has_usage = usage_obj is not None
        fallback_estimated = not (has_usage and hasattr(usage_obj, "total_tokens"))
        actual_used = (
            usage_obj.total_tokens
            if has_usage and hasattr(usage_obj, "total_tokens")
            else estimated_tokens
        )
        try:
            details = {
                "model": getattr(_cfg(), "MODEL", None),
                "has_usage": bool(has_usage),
                "used_estimated_tokens": bool(fallback_estimated),
            }
            if has_usage:
                for k in (
                    "total_tokens",
                    "prompt_tokens",
                    "completion_tokens",
                    "input_tokens",
                    "output_tokens",
                    "reasoning_tokens",
                ):
                    if hasattr(usage_obj, k):
                        details[k] = getattr(usage_obj, k)
            logger.info(f"{log_prefix} LLM token usage: {details}")
        except Exception:
            pass
        update_token_usage(actual_used, used_estimate=fallback_estimated, response=response)
        rate_limiter.RATE_LIMITER.add_request(actual_used, request_id=request_id)

        logger.debug(f"{log_prefix} Received response from the language model.")
        return response, None
    except Exception as e:
        error_msg = f"{error_message}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg


def process_response_by_type(response_type, response, response_message):
    """Route the response to appropriate handler based on type"""
    logger.debug(f"Handling response of type: {response_type}")

    if response_type == "tool_call":
        return handle_tool_call(response)
    elif response_type == "function_call":
        return handle(response_message.function_call)
    else:
        return process_direct_response(response_message)


def get_llm_initial_completion():
    """Get initial response from LLM for the query with rate limiting

    Routes to appropriate API based on config.RESPONSES_API setting.
    """
    # Check if responses API should be used
    if should_use_responses_adapter():
        logger.debug("Getting initial responses API response...")
        user_input = extract_user_input_from_history()
        if not user_input:
            return None, "No user input found in conversation history for responses API"

        return get_response_initial_completion(
            user_input, TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS
        )

    # Use conversations API
    logger.debug("Getting initial conversations API response...")
    return get_llm_completion(
        log_prefix="Initial request:",
        error_message="I apologize, but I encountered an error processing your request. Please try again",
    )
