"""Utility helpers for LLM processing moved out of core/llm.py for reuse and clarity.

This module contains lightweight helpers and adapters that the core llm orchestration
imports. It intentionally mirrors the behavior in src/monitor/core/llm.py at the time
of extraction; any future refactorings should update both caller sites as needed.
"""

import logging
import re

import litellm

try:
    import httpcore
except ImportError:
    httpcore = None

try:
    import httpx
except ImportError:
    httpx = None

try:
    from monitor.lib import rate_limiter
except Exception:
    rate_limiter = None

from typing import Any, Dict, List, Optional, Tuple, Union

from monitor import config
from monitor.lib.history import append_to_history_with_count
from monitor.lib.llm_model_utils import (
    DEFAULT_TOOL_TYPE,
    DESCRIPTION_KEY,
    NAME_KEY,
    OPENAI_PREFIX,
    PARAMETERS_PROPERTIES_KEY,
    PARAMETERS_REQUIRED_KEY,
    PARAMETERS_TYPE_OBJECT,
    TYPE_KEY,
    get_model_head,
    get_model_tail,
    effective_turn_effort,
    is_reasoning_model,
    normalize_tool_descriptors,
    resolve_turn_model,
    strip_openai_prefix,
)
from monitor.lib.llm_output_utils import (
    build_function_call_output_item,
    build_summarization_followup_params,
    serialize_tool_output,
)
from monitor.lib.llm_usage_utils import (
    compute_token_delta,
    safe_extract_total_tokens,
    truncate_to_token_limit,
)
from monitor.lib.message_utils import normalize_message, sanitize_messages
from monitor.lib.text_to_speech import TextToSpeech
from monitor.lib.tool_loading import function_descriptions

logger = logging.getLogger(__name__)

TTS = TextToSpeech()


class AttrDict(dict):
    """
    Dictionary subclass whose entries can be accessed by attributes (as well as normally).
    Useful for converting dict-style API responses to attribute-accessible objects.
    """
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        for key, value in self.items():
            setattr(self, key, self._wrap(value))

    def __setitem__(self, key, value):
        super(AttrDict, self).__setitem__(key, value)
        setattr(self, key, self._wrap(value))

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def _wrap(self, value):
        if isinstance(value, dict):
            return AttrDict(value)
        elif isinstance(value, list):
            return [self._wrap(item) for item in value]
        return value


def dict_to_attr(obj):
    if isinstance(obj, dict):
        return AttrDict({k: dict_to_attr(v) for k, v in obj.items()})
    elif isinstance(obj, list):
        return [dict_to_attr(v) for v in obj]
    else:
        return obj


def validate_tool_message_order(messages):
    """
    Validate that 'tool' role messages immediately follow an assistant message with matching tool_calls.
    Maintains a set of pending tool_call ids from the most recent assistant tool_calls.
    Clears the pending set after the first non-tool message following the assistant/tool_calls sequence.
    Raises ValueError if any 'tool' message violates the order or has unknown tool_call_id.
    Also validates that assistant messages with tool_calls contain a non-empty list and that each tool_call has an id.
    """
    pending = {}
    in_tool_phase = False
    for idx, msg in enumerate(messages):
        role = msg.get("role")
        if role == "assistant":
            tool_calls = msg.get("tool_calls", None)
            if tool_calls is not None:
                if not isinstance(tool_calls, list):
                    raise ValueError(f"Invalid assistant message at index {idx}: tool_calls must be a list when present.")
                if len(tool_calls) == 0:
                    raise ValueError(f"Invalid assistant message at index {idx}: tool_calls must not be an empty list.")
                for tc in tool_calls:
                    tc_id = None
                    if isinstance(tc, dict):
                        tc_id = tc.get("id")
                    else:
                        tc_id = getattr(tc, "id", None)
                    if not tc_id:
                        raise ValueError(f"Invalid assistant tool_call at index {idx}: missing id.")
            tool_calls = tool_calls or []
            pending = {tc.get("id"): True for tc in tool_calls if isinstance(tc, dict) and tc.get("id")}
            # If tool_calls are objects, include their ids as well
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    tc_id_obj = getattr(tc, "id", None)
                    if tc_id_obj:
                        pending[tc_id_obj] = True
            in_tool_phase = len(pending) > 0
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id")
            if not in_tool_phase or not pending or tool_call_id not in pending:
                raise ValueError(
                    f"Invalid tool message at index {idx}: unexpected tool_call_id '{tool_call_id}'. "
                    "Tool messages must immediately follow an assistant message with matching tool_calls."
                )
            pending.pop(tool_call_id, None)
        else:
            if in_tool_phase:
                pending = {}
                in_tool_phase = False


def determine_response_type(response_message):
    """Determine the type of response and how to handle it"""
    logger.debug("Determining response type...")

    if hasattr(response_message, 'tool_calls') and response_message.tool_calls and len(response_message.tool_calls) > 0:
        return "tool_call"
    elif hasattr(response_message, 'function_call') and response_message.function_call:
        return "function_call"
    else:
        return "direct"


def process_direct_response(response_message):
    """Process a direct (non-function-call) response from LLM"""
    from monitor.lib.token_management import count_message_tokens, update_token_usage

    logger.debug("Processing direct LLM response...")
    assistant_message = normalize_message(response_message)
    assistant_content = assistant_message.get("content", "")

    # Log and update conversation history
    if (config.CONVERSATION_LOG_FILE and not config.CONVERSATION_LOG_FILE.closed):
        try:
            config.CONVERSATION_LOG_FILE.write(f"AI: {assistant_content}\n")
        except Exception:
            logger.exception("Failed writing to conversation log file.")
    append_to_history_with_count(
        assistant_message,
        config.CONVERSATION_HISTORY,
        count_message_tokens,
        update_token_usage
    )

    if getattr(config, "LAST_INPUT_WAS_VOICE", False):
        try:
            TTS.speak(assistant_content)
        except Exception:
            logger.exception("TTS speak failed")
        config.LAST_INPUT_WAS_VOICE = False

    return assistant_content


def extract_tool_calls(response):
    """Extract and validate tool calls from LLM response"""
    from monitor.lib.token_management import count_message_tokens, update_token_usage
    
    # Defensive check for choices
    if not getattr(response, "choices", None) or len(response.choices) == 0:
        raise ValueError("Malformed response: missing choices for tool extraction")

    msg = response.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None) or []
    try:
        ids_presence = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                ids_presence.append(bool(tc.get("id")))
            else:
                ids_presence.append(bool(getattr(tc, "id", None)))
        logger.debug(f"Tool calls count: {len(tool_calls)}; all_have_ids={all(ids_presence)}")
    except Exception as e:
        logger.error(f"Unable to evaluate tool_call id presence: {e}")
    normalized_msg = normalize_message(msg)
    # Ensure we have a mutable dict to work with
    if not isinstance(normalized_msg, dict):
        try:
            if hasattr(normalized_msg, "to_dict"):
                normalized_msg = normalized_msg.to_dict()
            elif hasattr(normalized_msg, "__dict__"):
                normalized_msg = {k: v for k, v in normalized_msg.__dict__.items() if not k.startswith("_")}
            else:
                normalized_msg = dict(normalized_msg)
        except Exception:
            normalized_msg = {"role": getattr(msg, "role", "assistant"), "content": getattr(msg, "content", None)}
    # Rebuild tool_calls into list of dicts when present and non-empty; otherwise remove key
    rebuilt_tool_calls = []
    if isinstance(tool_calls, list) and len(tool_calls) > 0:
        for tc in tool_calls:
            if isinstance(tc, dict):
                rebuilt_tool_calls.append(tc)
            else:
                try:
                    if hasattr(tc, "to_dict"):
                        rebuilt_tool_calls.append(tc.to_dict())
                    elif hasattr(tc, "__dict__"):
                        rebuilt_tool_calls.append({k: v for k, v in tc.__dict__.items() if not k.startswith("_")})
                    else:
                        rebuilt_tool_calls.append({"id": getattr(tc, "id", None)})
                except Exception:
                    rebuilt_tool_calls.append({"id": getattr(tc, "id", None)})
        normalized_msg["tool_calls"] = rebuilt_tool_calls
    else:
        if "tool_calls" in normalized_msg:
            try:
                del normalized_msg["tool_calls"]
            except Exception:
                normalized_msg["tool_calls"] = []
                try:
                    del normalized_msg["tool_calls"]
                except Exception:
                    pass
    # Sanitize and append the single message
    try:
        sanitized_list = sanitize_messages([normalized_msg])
    except Exception as e:
        logger.error(f"sanitize_messages failed in extract_tool_calls: {e}")
        sanitized_list = [normalized_msg]
    sanitized_msg = sanitized_list[0] if isinstance(sanitized_list, list) and sanitized_list else normalized_msg
    append_to_history_with_count(
        sanitized_msg,
        config.CONVERSATION_HISTORY,
        count_message_tokens,
        update_token_usage
    )
    # Return the sanitized message's tool_calls as a list of dicts, default empty
    return sanitized_msg.get("tool_calls", []) if isinstance(sanitized_msg, dict) else []


def process_response_by_finish_reason(response):
    """Process the LLM response and determine next action"""
    choices = getattr(response, "choices", None)
    if choices is None or len(choices) == 0:
        raise ValueError("Malformed response: missing choices when processing finish reason")

    finish_reason = (choices[0].finish_reason or '').lower()

    # openai uses 'refusal'
    # grok uses 'content_filter'
    # gemini uses 'safety'
    if finish_reason == "refusal" or finish_reason == "content_filter" or finish_reason == "safety":
        logger.error("The request was refused due to policy violations.")
        # Remove the last turn (user input and any assistant response) from conversation history
        if len(config.CONVERSATION_HISTORY) >= 1:
            # Remove the last user message that caused the refusal
            last_message = config.CONVERSATION_HISTORY[-1]
            if last_message.get('role') == 'user':
                config.CONVERSATION_HISTORY.pop()
                # Pop the matching per-turn cost bucket in lockstep. That
                # bucket was opened when the user message landed in history
                # (see append_to_history_with_count). With no LLM cost
                # recorded for a refused call, leaving it would surface as
                # a phantom $0.00 last-turn entry in the U: indicator that
                # never goes away.
                try:
                    turn_costs = getattr(config, "TURN_COSTS_USD", None)
                    if isinstance(turn_costs, list) and turn_costs:
                        turn_costs.pop()
                        config.TURN_COSTS_USD = turn_costs
                except Exception:
                    logger.debug(
                        "Failed to pop TURN_COSTS_USD bucket on refusal", exc_info=True
                    )
                try:
                    round_trips = getattr(config, "TURN_ROUND_TRIPS", None)
                    if isinstance(round_trips, list) and round_trips:
                        round_trips.pop()
                        config.TURN_ROUND_TRIPS = round_trips
                except Exception:
                    logger.debug(
                        "Failed to pop TURN_ROUND_TRIPS bucket on refusal", exc_info=True
                    )
                logger.debug("Removed user message that caused refusal from conversation history")

            # If there's an assistant message that was also added, remove it too
            if len(config.CONVERSATION_HISTORY) >= 1:
                second_last_message = config.CONVERSATION_HISTORY[-1]
                if second_last_message.get('role') == 'assistant':
                    config.CONVERSATION_HISTORY.pop()
                    logger.debug("Removed assistant message from conversation history due to refusal")

        return "Request was refused."

    # openai uses length
    # gemini uses max_tokens
    if finish_reason == "length" or finish_reason == "max_tokens":
        logger.error("The conversation was too long for the context window.")
        return "Length too long."

    if finish_reason == "tool_calls":
        return None  # Indicate need for another tool call

    if finish_reason == "stop":
        assistant_content = choices[0].message.content
        if (config.CONVERSATION_LOG_FILE and not config.CONVERSATION_LOG_FILE.closed):
            try:
                config.CONVERSATION_LOG_FILE.write(f"AI: {assistant_content}\n")
            except Exception:
                logger.exception("Failed writing assistant content to conversation log file")

        if assistant_content is None or assistant_content == {}:
            return "Ok."
        return assistant_content

    if config.MODEL and isinstance(config.MODEL, str) and "xai/grok" in config.MODEL and finish_reason == "":
        return None  # Indicate need for another tool call

    logger.error(f"Unexpected finish_reason: {finish_reason} - {choices[0]}")
    return f"Unexpected finish reason: {finish_reason}"

def call_litellm_completion(model: str, messages: list, tool_descriptions: List[Dict[str, Any]], gemini_tool_descriptions: List[Dict[str, Any]]):
    """
    Wrapper that adds `reasoning_effort` and `max_completion_tokens` when the
    model name contains the configured reasoning model prefix.

    Args:
        model: The full model identifier, e.g., 'openai/o3-2025-04-16'
        messages: The list of chat messages for the request.

    Returns:
        The litellm completion response.
    """
    kwargs = {
        "model": model,
        "messages": messages,
        "tools": function_descriptions(
            tool_descriptions, gemini_tool_descriptions, model
        ),
        "drop_params": True,
    }

    prefix = getattr(config, "REASONING_MODEL_PREFIX", None)
    if isinstance(prefix, str):
        prefix = prefix.strip()
    is_reasoning = False
    if isinstance(prefix, str) and prefix:
        try:
            pattern = re.compile(re.escape(prefix), re.IGNORECASE)
            if pattern.search(model):
                is_reasoning = True
                # Per-turn override (set by the auto-bump heuristic in
                # prepare_query_context, or by tool-failure escalation in
                # tooling.py) wins over the configured default for the duration
                # of this user turn. The override is one-way (only ever bumps
                # up — to medium or, on tool failure, high), so reading it
                # unconditionally never causes a surprise downgrade.
                override = getattr(config, "CURRENT_TURN_REASONING_OVERRIDE", None)
                collation = bool(getattr(config, "CURRENT_TURN_IS_COLLATION", False))
                effective_effort = effective_turn_effort(
                    config.REASONING_EFFORT,
                    override,
                    collation_active=collation,
                    orchestrator_effort=getattr(config, "ORCHESTRATOR_REASONING_EFFORT", None),
                )
                effective_max = config.REASONING_MAX_COMPLETION_TOKENS
                # Single-turn, transient model swap (kwargs only, never set_model):
                #   - collation/synthesis turn -> ORCHESTRATOR_MODEL
                #   - else a reasoning override -> ADV_REASONING_MODEL
                # So the configured default model, gauges, and session state are
                # all untouched, and the orchestrator backs down to MODEL after.
                swapped = resolve_turn_model(
                    model,
                    getattr(config, "ADV_REASONING_MODEL", None),
                    bool(override),
                    prefix,
                    orchestrator_model=getattr(config, "ORCHESTRATOR_MODEL", None),
                    collation_active=collation,
                )
                if swapped != model:
                    kwargs["model"] = swapped
                    kwargs["tools"] = function_descriptions(
                        tool_descriptions, gemini_tool_descriptions, swapped
                    )
                    # The ADV output-window cap applies only on an ADV swap.
                    if swapped == getattr(config, "ADV_REASONING_MODEL", None):
                        adv_out = getattr(config, "ADV_REASONING_MODEL_OUTPUT_WINDOW", None)
                        if (
                            isinstance(adv_out, int)
                            and adv_out > 0
                            and isinstance(effective_max, int)
                            and effective_max > 0
                        ):
                            effective_max = min(effective_max, adv_out)
                kwargs.update(
                    reasoning_effort=effective_effort,
                    max_completion_tokens=effective_max,
                    temperature=1,
                )
        except re.error:
            pass

    # For non-reasoning calls, apply the general MAX_COMPLETION_TOKENS cap so
    # the provider truncates long completions instead of running to whatever
    # the model picks on its own. Reasoning models already set their own,
    # larger cap above — don't overwrite it. drop_params=True lets litellm
    # translate the param name per provider.
    if not is_reasoning:
        _cap = getattr(config, "MAX_COMPLETION_TOKENS", None)
        if isinstance(_cap, int) and _cap > 0:
            kwargs["max_completion_tokens"] = _cap

    return litellm.completion(**kwargs)


ROLE_KEY = "role"
SYSTEM_ROLE = "system"
CONTENT_KEY = "content"
USER_ROLE = "user"

def prepare_response_messages(user_input):
    """Prepare messages for responses API format.

    The responses API typically expects a simpler format focused on the current request
    rather than full conversation history.

    Args:
        user_input (str): The current user input/query

    Returns:
        list: Formatted messages for responses API
    """
    try:
        # For responses API, we focus on the current request
        # Add system message if preferences are configured
        messages = []

        from monitor.lib.preferences import PREFERENCE_PROMPT

        if PREFERENCE_PROMPT:
            messages.append({ROLE_KEY: SYSTEM_ROLE, CONTENT_KEY: PREFERENCE_PROMPT})

        # Add the user input
        messages.append({ROLE_KEY: USER_ROLE, CONTENT_KEY: user_input})

        # Sanitize messages before sending
        messages = sanitize_messages(messages)

        logger.debug(f"Prepared {len(messages)} messages for responses API")
        return messages

    except Exception as e:
        logger.error(f"Error preparing response messages: {e}", exc_info=True)
        raise

def estimate_response_tokens(messages):
    """Estimate token count for responses API messages."""
    from monitor.lib.token_management import count_message_tokens, update_token_usage

    try:
        estimated_tokens = 0
        for msg in messages:
            normalized_msg = normalize_message(msg)
            estimated_tokens += count_message_tokens(normalized_msg)

        logger.debug(f"Estimated {estimated_tokens} tokens for responses API")
        return estimated_tokens

    except Exception as e:
        logger.error(f"Error estimating response tokens: {e}", exc_info=True)
        return 0

def get_tools_for_model(tool_descriptions, gemini_tool_descriptions):
    """Get appropriate tool definitions based on the model type.

    Returns:
        tuple: (tools, tool_choice) where tools is the tool definitions and
               tool_choice is the tool selection strategy
    """
    try:
        model_lower = config.MODEL.lower()

        # Check if tools are disabled
        if getattr(config, "DISABLE_TOOLS", False):
            logger.debug("Tools disabled by configuration")
            return None, None

        # Determine which tools to use based on model
        if "gemini" in model_lower:
            tools = gemini_tool_descriptions
            logger.debug(
                f"Using Gemini tool descriptions ({len(tools) if tools else 0} tools)"
            )
        else:
            tools = function_descriptions(tool_descriptions, gemini_tool_descriptions, model_lower)
            logger.debug(
                f"Using function descriptions ({len(tools) if tools else 0} tools)"
            )

        # Normalize tool descriptors to a consistent flat shape for downstream usage
        if tools:
            try:
                tools = normalize_tool_descriptors(tools)
            except Exception:
                logger.exception("Failed to normalize tool descriptors, proceeding with original tools")

        # Set tool choice strategy
        tool_choice = "auto" if tools else None

        return tools, tool_choice

    except Exception as e:
        logger.error(f"Error getting tools for model: {e}", exc_info=True)
        return None, None

CHOICES_KEY = "choices"
MESSAGE_KEY = "message"

def convert_response_format(api_response):
    """Convert responses API response to expected format.

    Ensures the response format matches what the rest of the system expects.

    Args:
        api_response (dict): Raw or normalized API response

    Returns:
        AttrDict: Converted response with attribute access
    """
    try:
        # Convert to attribute-accessible format
        response = dict_to_attr(api_response)

        # Validate expected response structure
        if not hasattr(response, CHOICES_KEY) or not response.choices:
            raise ValueError("Invalid response format: missing choices")

        if len(response.choices) == 0:
            raise ValueError("Invalid response format: empty choices")

        first_choice = response.choices[0]
        if not hasattr(first_choice, MESSAGE_KEY):
            raise ValueError("Invalid response format: missing message in choice")

        logger.debug("Successfully converted response format")
        return response

    except Exception as e:
        logger.error(f"Error converting response format: {e}", exc_info=True)
        raise

MAX_ERROR_INPUT_SNIPPET = 100

def handle_response_errors(error, user_input=None):
    """Handle responses API specific errors with appropriate logging.

    Args:
        error (Exception): The error that occurred
        user_input (str, optional): The original user input for context

    Returns:
        tuple: (None, error_message) following llm.py error format
    """
    # Detect network/connectivity-related errors and handle them specially.
    network_error_classes = []
    if httpcore is not None:
        try:
            network_error_classes.append(httpcore.ConnectError)
        except Exception:
            # If httpcore doesn't expose ConnectError as expected, ignore.
            pass
    if httpx is not None:
        try:
            network_error_classes.append(httpx.ConnectError)
        except Exception:
            # If httpx doesn't expose ConnectError as expected, ignore.
            pass
    # OSError covers many low-level network errors (e.g., socket errors).
    network_error_classes.append(OSError)

    is_network_error = False
    try:
        is_network_error = any(isinstance(error, cls) for cls in network_error_classes if cls is not None)
    except Exception:
        # If isinstance checks fail for some reason, fall back to string matching below.
        is_network_error = False

    error_str = str(error) if error is not None else ""
    if not is_network_error and isinstance(error_str, str) and "network is unreachable" in error_str.lower():
        is_network_error = True

    if is_network_error:
        # Log a warning without traceback to avoid leaking internal details, then raise a sanitized error.
        logger.warning("Network error detected while calling Responses API; marking as network unreachable.")
        raise RuntimeError("Network unreachable") from None

    error_context = (
        f" for input: {user_input[:MAX_ERROR_INPUT_SNIPPET]}..."
        if user_input and len(user_input) > MAX_ERROR_INPUT_SNIPPET
        else f" for input: {user_input}"
        if user_input
        else ""
    )

    if "rate limit" in str(error).lower():
        error_msg = f"Responses API rate limit exceeded{error_context}. Please try again later."
        logger.error(f"Rate limit error: {error}", exc_info=True)
    elif "authentication" in str(error).lower() or "unauthorized" in str(error).lower():
        error_msg = f"Responses API authentication failed{error_context}. Please check your API credentials."
        logger.error(f"Authentication error: {error}", exc_info=True)
    elif "quota" in str(error).lower() or "billing" in str(error).lower():
        error_msg = f"Responses API quota exceeded{error_context}. Please check your account status."
        logger.error(f"Quota error: {error}", exc_info=True)
    elif "timeout" in str(error).lower():
        error_msg = f"Responses API request timed out{error_context}. Please try again."
        logger.error(f"Timeout error: {error}", exc_info=True)
    else:
        error_msg = f"Responses API error{error_context}: {str(error)}"
        logger.error(f"General responses API error: {error}", exc_info=True)

    return None, error_msg


def apply_usage_delta(usage: Any, previous_total: Optional[Union[int, float]] = None) -> Tuple[Optional[int], int]:
    """Apply a usage update by computing the delta and updating token counters.

    Args:
        usage: The usage payload as a dict, object, number, or string.
        previous_total: Optional previous total count to compute a delta against.

    Returns:
        A tuple of ``(current_total_or_none, delta_int)``.

    Raises:
        ValueError: If ``usage`` cannot be coerced to a token count.
    """
    current = safe_extract_total_tokens(usage)
    delta = compute_token_delta(current, previous_total)

    if delta > 0:
        try:
            from monitor.lib import token_management

            token_management.update_token_usage(delta)
        except Exception:
            logger.exception("apply_usage_delta: update_token_usage failed")

        if rate_limiter is not None:
            candidate_names = (
                "add_usage",
                "add_tokens",
                "consume",
                "consume_tokens",
                "record_usage",
                "record",
            )
            for name in candidate_names:
                fn = getattr(rate_limiter, name, None)
                if callable(fn):
                    try:
                        fn(delta)
                        break
                    except Exception:
                        logger.debug(
                            "apply_usage_delta: rate_limiter.%s failed",
                            name,
                            exc_info=True,
                        )

    try:
        if delta > 0:
            setattr(config, "CANONICAL_TOKEN_USAGE", current)
    except Exception:
        logger.debug(
            "apply_usage_delta: unable to set config.CANONICAL_TOKEN_USAGE",
            exc_info=True,
        )

    return current, delta


