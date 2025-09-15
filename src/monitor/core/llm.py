import logging
import litellm
import monitor.lib.llm_utils as llm_utils

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
    generate_conversation_summary,
    reset_conversation_with_summary,
)
from monitor.lib.token_management import count_message_tokens, update_token_usage
from monitor.lib.system_prompt import SYSTEM_PROMPT
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
      - MODEL is a string and starts with REASONING_MODEL_PREFIX (case-sensitive)

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
        return model.startswith(prefix)
    except Exception as e:
        logger.debug(f"should_use_responses_adapter check failed: {e}", exc_info=True)
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


def get_llm_completion(log_prefix="", error_message="Error during litellm completion"):
    """Common logic for getting completion from LLM with error handling and rate limiting.
    Token counting and updates use canonical helpers from monitor.lib/token_management.py.

    Adapter gating is performed via should_use_responses_adapter(), which returns True only when:
      - RESPONSES_API is True
      - REASONING_MODEL_PREFIX is a non-empty string
      - MODEL is a string that starts with REASONING_MODEL_PREFIX

    If the adapter is not used, falls back to the conversations API.
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

        estimated_request = estimated_tokens + (
            _cfg().REASONING_MAX_COMPLETION_TOKENS
            if isinstance(_cfg().REASONING_MODEL_PREFIX, str)
            and isinstance(_cfg().MODEL, str)
            and _cfg().REASONING_MODEL_PREFIX.lower() in _cfg().MODEL.lower()
            else 0
        )

        if estimated_request > _cfg().MODEL_MAX_TPM:
            if (
                getattr(_cfg(), "ENABLE_AUTO_SUMMARIZE_ON_LIMIT", False)
                and not summarization_attempted
            ):
                logger.info("Attempting auto-summarization due to token limit...")
                try:
                    summary_response = generate_conversation_summary(
                        SYSTEM_PROMPT,
                        _cfg().CONVERSATION_HISTORY,
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

                    last_user_content = ""
                    for m in reversed(_cfg().CONVERSATION_HISTORY):
                        if m.get("role") == "user":
                            last_user_content = m.get("content", "")
                            break

                    reset_conversation_with_summary(
                        summary_content or "",
                        SYSTEM_PROMPT,
                        last_user_content,
                        _cfg().CONVERSATION_HISTORY,
                        append_to_history_with_count,
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
                    estimated_request = estimated_tokens + (
                        _cfg().REASONING_MAX_COMPLETION_TOKENS
                        if isinstance(_cfg().REASONING_MODEL_PREFIX, str)
                        and isinstance(_cfg().MODEL, str)
                        and _cfg().REASONING_MODEL_PREFIX.lower()
                        in _cfg().MODEL.lower()
                        else 0
                    )
                    logger.info("Auto-summarization complete; retrying request.")
                except Exception as se:
                    logger.error(f"Auto-summarization failed: {se}", exc_info=True)

        if estimated_request > _cfg().MODEL_MAX_TPM:
            return None, (
                f"Input too large: {estimated_request} tokens "
                f"vs model limit {_cfg().MODEL_MAX_TPM}. Cannot send request. "
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
                    summary_response = generate_conversation_summary(
                        SYSTEM_PROMPT,
                        _cfg().CONVERSATION_HISTORY,
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

                    last_user_content = ""
                    for m in reversed(_cfg().CONVERSATION_HISTORY):
                        if m.get("role") == "user":
                            last_user_content = m.get("content", "")
                            break

                    reset_conversation_with_summary(
                        summary_content or "",
                        SYSTEM_PROMPT,
                        last_user_content,
                        _cfg().CONVERSATION_HISTORY,
                        append_to_history_with_count,
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
                    estimated_request = estimated_tokens + (
                        _cfg().REASONING_MAX_COMPLETION_TOKENS
                        if isinstance(_cfg().REASONING_MODEL_PREFIX, str)
                        and isinstance(_cfg().MODEL, str)
                        and _cfg().REASONING_MODEL_PREFIX.lower()
                        in _cfg().MODEL.lower()
                        else 0
                    )
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
                    f"Input too large: {estimated_request} tokens. Model limit {_cfg().MODEL_MAX_TPM} tokens. "
                    "Reduce the size of your request."
                )

        # Final validation just before making the completion call
        try:
            validate_tool_message_order(messages)
        except ValueError as ve:
            logger.error(f"Message validation failed (pre-completion): {ve}")
            return None, str(ve)

        with progress_dots():
            response = call_litellm_completion(
                _cfg().MODEL, messages, TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS
            )

        # Convert response (and possibly inner objects) to attribute-access-friendly structures
        response = dict_to_attr(response)

        # Record actual usage using canonical update
        actual_used = (
            response.usage.total_tokens
            if hasattr(response, "usage") and hasattr(response.usage, "total_tokens")
            else estimated_tokens
        )
        update_token_usage(actual_used)
        rate_limiter.RATE_LIMITER.add_request(actual_used)

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
