"""Utility helpers for LLM processing moved out of core/llm.py for reuse and clarity.

This module contains lightweight helpers and adapters that the core llm orchestration
imports. It intentionally mirrors the behavior in src/monitor/core/llm.py at the time
of extraction; any future refactorings should update both caller sites as needed.
"""

import logging
import re
import json
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

from typing import List, Dict, Any, Optional, Union, Tuple

from monitor import config
from monitor.lib.tool_loading import function_descriptions
from monitor.lib.message_utils import normalize_message, sanitize_messages
from monitor.lib.history import append_to_history_with_count
from monitor.lib.text_to_speech import TextToSpeech

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
                # prepare_query_context) wins over the configured default
                # for the duration of this user turn. The override is one-
                # way (only bumps up to high), so reading it unconditionally
                # never causes a surprise downgrade.
                effective_effort = (
                    getattr(config, "CURRENT_TURN_REASONING_OVERRIDE", None)
                    or config.REASONING_EFFORT
                )
                kwargs.update(
                    reasoning_effort=effective_effort,
                    max_completion_tokens=config.REASONING_MAX_COMPLETION_TOKENS,
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

OPENAI_PREFIX = "openai/"

def strip_openai_prefix(model_name):
    """Remove a leading 'openai/' prefix from a model name, case-insensitively.

    Args:
        model_name (str or None): The model name to normalize.

    Returns:
        str or original value: The model name with a leading 'openai/' removed
        if present (case-insensitive). If model_name is falsy or not a str,
        returns model_name unchanged.

    Examples:
        >>> strip_openai_prefix("openai/gpt-4")
        'gpt-4'
        >>> strip_openai_prefix("OpenAI/GPT-4o")
        'GPT-4o'
        >>> strip_openai_prefix(None) is None
        True
        >>> strip_openai_prefix(123)
        123
    """
    if not model_name or not isinstance(model_name, str):
        return model_name
    lower = model_name.lower()
    prefix = OPENAI_PREFIX
    if lower.startswith(prefix):
        return model_name[len(prefix) :]
    return model_name

def is_reasoning_model(model: Optional[str], prefix: Optional[str]) -> bool:
    """Check whether a model name starts with a given reasoning prefix.

    This helper performs a case-insensitive startswith check and returns True
    only when both inputs are strings.

    Args:
        model: The model identifier to check.
        prefix: The prefix indicating a reasoning model.

    Returns:
        bool: True if model and prefix are strings and model starts with prefix
        (case-insensitive); otherwise False.
    """
    if not isinstance(model, str) or not isinstance(prefix, str):
        return False
    return model.lower().startswith(prefix.lower())

def get_model_tail(model: str) -> str:
    """
    Return the substring after the last '/' in a model string.

    Args:
        model: A model identifier like "aaaa/bbbb".

    Returns:
        The part after the final slash (e.g., "bbbb"). If there is no slash,
        returns the trimmed input. Trailing slashes are ignored.
    """
    s = model.strip()
    if not s:
        return s
    s = s.rstrip("/")
    return s.split("/")[-1]

def get_model_head(model: str, mapping: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    """Return the mapping value for the best-matching key found in the model tail.

    This helper obtains the model tail via get_model_tail(model) and performs
    a case-insensitive substring match of each string key in `mapping`
    against the tail. When multiple keys match, the longest key is preferred
    (to favor more specific matches). If `mapping` is None or no keys match,
    returns None.

    Args:
        model: Model identifier string (e.g., "openai/gpt-4o-mini").
        mapping: Optional dictionary mapping substring keys to desired values.

    Returns:
        The value from `mapping` corresponding to the longest matching key, or
        None when no suitable key is found.
    """
    if not mapping:
        return None

    try:
        tail = get_model_tail(model) if isinstance(model, str) else str(model or "")
    except Exception:
        try:
            tail = str(model)
        except Exception:
            return None

    tail_lower = tail.lower()
    # Collect keys that are strings and whose lowercase form is a substring of tail_lower
    candidates = [k for k in mapping.keys() if isinstance(k, str) and k.lower() in tail_lower]
    if not candidates:
        return None

    # Prefer longer keys to match more specific entries
    best_key = max(candidates, key=len)
    try:
        return mapping.get(best_key)
    except Exception:
        return None

TYPE_KEY = "type"
NAME_KEY = "name"
DESCRIPTION_KEY = "description"
DEFAULT_TOOL_TYPE = "function"
PARAMETERS_PROPERTIES_KEY = "properties"
PARAMETERS_REQUIRED_KEY = "required"
PARAMETERS_TYPE_OBJECT = "object"

def normalize_tool_descriptors(tool_list):
    """Normalize a list of tool descriptor dicts into a flat, consistent shape.

    The function accepts tool descriptor entries in one of two common shapes:
      1) Flat descriptors:
         { 'type': 'function', 'name': 'foo', 'description': '...', 'parameters': { ... } }
      2) Nested descriptors:
         { 'type': 'function', 'function': { 'name': 'foo', 'description': '...', 'parameters': {...} } }

    Returns a new list where each descriptor is a dict with at minimum:
      { 'type': 'function', 'name': <str>, 'description': <str>, 'parameters': {
            'type': 'object', 'properties': {...}, 'required': [...] (if present)
        }
      }

    Defensive behavior:
    - Skips non-dict entries.
    - Skips entries without a valid string 'name'.
    - Ensures 'parameters' is a dict; sets parameters['type'] == 'object'.
    - Ensures parameters['properties'] exists as a dict.
    - If 'required' exists, ensures it's a list (or converts/cleans to an empty list).
    - Logs exceptions per-entry but continues processing other entries.
    """
    if not tool_list:
        return tool_list

    normalized = []
    for idx, entry in enumerate(tool_list):
        try:
            if not isinstance(entry, dict):
                logger.debug(
                    f"Skipping non-dict tool descriptor at index {idx}: {type(entry)}"
                )
                continue

            # Support nested 'function' wrapper
            nested = entry.get("function") if isinstance(entry.get("function"), dict) else None

            # Derive core fields with nested taking precedence
            name = None
            description = None
            parameters = None
            type_val = None

            if nested:
                name = nested.get(NAME_KEY) or entry.get(NAME_KEY)
                description = nested.get(DESCRIPTION_KEY) or entry.get(DESCRIPTION_KEY) or ""
                parameters = nested.get("parameters") or entry.get("parameters")
                type_val = entry.get(TYPE_KEY) or nested.get(TYPE_KEY) or DEFAULT_TOOL_TYPE
            else:
                name = entry.get(NAME_KEY)
                description = entry.get(DESCRIPTION_KEY) or entry.get("doc") or ""
                parameters = entry.get("parameters")
                type_val = entry.get(TYPE_KEY) or DEFAULT_TOOL_TYPE

            # Validate name
            if not name or not isinstance(name, str):
                logger.debug(
                    f"Skipping tool descriptor without valid name at index {idx}: {name}"
                )
                continue

            # Ensure parameters is a dict
            if not isinstance(parameters, dict):
                parameters = {}

            # Work on a shallow copy to avoid mutating original
            parameters = dict(parameters)

            # Ensure parameters['type'] == 'object'
            if parameters.get(TYPE_KEY) != PARAMETERS_TYPE_OBJECT:
                parameters[TYPE_KEY] = PARAMETERS_TYPE_OBJECT

            # Ensure properties exists as a dict
            props = parameters.get(PARAMETERS_PROPERTIES_KEY)
            if not isinstance(props, dict):
                parameters[PARAMETERS_PROPERTIES_KEY] = {}

            # Ensure 'required' is a list if present; coerce if possible
            if PARAMETERS_REQUIRED_KEY in parameters:
                req = parameters.get(PARAMETERS_REQUIRED_KEY)
                if isinstance(req, list):
                    # fine
                    pass
                elif hasattr(req, "__iter__") and not isinstance(req, (str, bytes, dict)):
                    try:
                        parameters[PARAMETERS_REQUIRED_KEY] = list(req)
                    except Exception:
                        parameters[PARAMETERS_REQUIRED_KEY] = []
                else:
                    parameters[PARAMETERS_REQUIRED_KEY] = []

            normalized.append(
                {
                    TYPE_KEY: type_val,
                    NAME_KEY: name,
                    DESCRIPTION_KEY: description or "",
                    "parameters": parameters,
                }
            )

        except Exception as e:
            logger.exception(f"Error normalizing tool descriptor at index {idx}: {e}")
            # Continue processing other entries despite the error
            continue

    return normalized

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

def safe_extract_total_tokens(usage: Any) -> Optional[int]:
    """Safely extract a canonical total token count from a usage-like object.

    This helper centralizes coercion logic for the various shapes a "usage"
    response can take across models and response formats. It attempts to
    coerce `usage` into a non-negative integer representing total tokens.

    Supported input shapes:
    - None -> returns None
    - int/float -> coerced to int and clamped to >= 0
    - numeric strings -> parsed to int (or float then int) and clamped
    - dicts -> common keys checked in order:
        'total_tokens', 'total', 'total_used', 'usage', or a sum of
        'prompt_tokens' + 'completion_tokens' when present.
    - objects -> will look for attributes with the names used above and recurse

    Args:
        usage: The usage value (dict, object, number, or string).

    Returns:
        Optional[int]: The extracted total token count, or None if input was None.

    Raises:
        ValueError: If the input cannot be coerced into a token count.
    """
    if usage is None:
        return None

    # Direct numeric types
    if isinstance(usage, int):
        return max(0, usage)
    if isinstance(usage, float):
        try:
            return max(0, int(usage))
        except Exception:
            return max(0, int(float(usage)))

    # Strings that might contain numbers
    if isinstance(usage, str):
        usage_str = usage.strip()
        if usage_str == "":
            raise ValueError("Empty string provided for usage")
        try:
            return max(0, int(usage_str))
        except Exception:
            try:
                return max(0, int(float(usage_str)))
            except Exception:
                raise ValueError(f"Unable to parse numeric string for usage: {usage!r}")

    # Dict-like structures
    if isinstance(usage, dict):
        # Preferred keys in order
        preferred = ("total_tokens", "total", "total_used", "usage", "tokens")
        for key in preferred:
            if key in usage and usage.get(key) is not None:
                return safe_extract_total_tokens(usage.get(key))
        # Fallback: sum prompt_tokens + completion_tokens
        if "prompt_tokens" in usage or "completion_tokens" in usage:
            try:
                prompt = usage.get("prompt_tokens", 0) or 0
                completion = usage.get("completion_tokens", 0) or 0
                return max(0, int(prompt) + int(completion))
            except Exception:
                # fall through to error below
                pass
        raise ValueError(f"Unable to coerce total tokens from usage dict: {usage!r}")

    # Object-like structures: attempt attribute access
    # Common attribute names used by various SDKs
    attr_candidates = ("total_tokens", "total", "total_used", "usage", "tokens", "prompt_tokens", "completion_tokens")
    for attr in attr_candidates:
        if hasattr(usage, attr):
            try:
                return safe_extract_total_tokens(getattr(usage, attr))
            except Exception:
                # try next candidate
                continue

    # Last-resort: try to coerce using __dict__ if available
    if hasattr(usage, "__dict__"):
        try:
            return safe_extract_total_tokens({k: v for k, v in usage.__dict__.items()})
        except Exception:
            pass

    raise ValueError(f"Unable to coerce total tokens from usage: {usage!r}")

def compute_token_delta(current_total: Optional[Union[int, float]], previous_total: Optional[Union[int, float]]) -> int:
    """Compute a safe, non-negative delta between two token totals.

    This function centralizes the logic for computing how many new tokens were
    consumed given a potentially new `current_total` and a prior `previous_total`.

    Behavior:
    - If current_total is None -> returns 0
    - If previous_total is None -> returns max(0, int(current_total))
    - Otherwise returns max(0, int(current_total) - int(previous_total))

    Args:
        current_total: The current canonical total token count (or None).
        previous_total: The previous total token count (or None).

    Returns:
        int: Non-negative integer delta representing additional tokens used.
    """
    if current_total is None:
        return 0
    try:
        current = int(current_total)
    except Exception:
        try:
            current = int(float(current_total))
        except Exception:
            logger.debug(f"compute_token_delta: unable to coerce current_total={current_total!r}")
            return 0

    if previous_total is None:
        return max(0, current)

    try:
        prev = int(previous_total)
    except Exception:
        try:
            prev = int(float(previous_total))
        except Exception:
            logger.debug(f"compute_token_delta: unable to coerce previous_total={previous_total!r}")
            prev = 0

    return max(0, current - prev)

def apply_usage_delta(usage: Any, previous_total: Optional[Union[int, float]] = None) -> Tuple[Optional[int], int]:
    """Apply a usage update by computing the delta and updating token counters.

    This convenience helper performs the following steps:
    1. Safely extract the canonical total token count from `usage` using
       `safe_extract_total_tokens`.
    2. Compute a non-negative delta against `previous_total` using
       `compute_token_delta`.
    3. If a positive delta is observed:
         - Attempt to call the project's `update_token_usage` to register the delta.
         - Attempt to inform an optional rate limiter module (when available)
           using common function names if present.
    4. Attempt to record the canonical current total on the `config` module as
       `CANONICAL_TOKEN_USAGE` for other parts of the system to inspect.

    The helper is defensive and will log exceptions rather than raise in most
    update-path scenarios; it will raise if the `usage` value cannot be
    interpreted as a token count.

    Args:
        usage: The usage payload (dict/object/number/string).
        previous_total: Optional previous total count to compute a delta against.

    Returns:
        tuple:
            (current_total_or_none, delta_int)
            - current_total_or_none: The canonical current total tokens (or None if input was None).
            - delta_int: The non-negative delta that was applied (0 when none).

    Raises:
        ValueError: If the provided `usage` cannot be coerced to a token count.
    """
    try:
        current = safe_extract_total_tokens(usage)
    except ValueError:
        logger.debug("apply_usage_delta: could not extract total tokens from usage; skipping updates.")
        raise

    delta = compute_token_delta(current, previous_total)

    if delta > 0:
        # Update project-level token usage helper if available
        try:
            from monitor.lib import token_management as token_management
            token_management.update_token_usage(delta)
        except Exception:
            logger.exception("apply_usage_delta: update_token_usage failed")

        # Attempt to notify a rate limiter if one is available.
        if rate_limiter is not None:
            # Try a set of common function names used across codebases.
            candidate_names = ("add_usage", "add_tokens", "consume", "consume_tokens", "record_usage", "record")
            for name in candidate_names:
                fn = getattr(rate_limiter, name, None)
                if callable(fn):
                    try:
                        fn(delta)
                        break
                    except Exception:
                        logger.debug(f"apply_usage_delta: rate_limiter.{name} failed", exc_info=True)

    # Persist canonical total on config for visibility; swallow errors if not possible.
    try:
        if delta > 0:
            setattr(config, "CANONICAL_TOKEN_USAGE", current)
    except Exception:
        logger.debug("apply_usage_delta: unable to set config.CANONICAL_TOKEN_USAGE", exc_info=True)

    return current, delta

def truncate_to_token_limit(text: str, token_limit: int, model: Optional[str] = None) -> str:
    """Truncate text to a given token limit.

    This helper attempts to use tiktoken to perform token-aware truncation for
    a provided model. If tiktoken is unavailable or encoding/decoding fails,
    it falls back to a conservative character-based truncation using an
    approximate average characters-per-token heuristic.

    The function tries to preserve as much content as possible and appends
    the sentinel string "...[TRUNCATED]" when truncation occurs.

    Args:
        text (str): The input text to truncate.
        token_limit (int): Maximum allowed token count. Non-positive values
            will result in an empty (or sentinel-only) return.
        model (Optional[str]): Optional model name to inform tiktoken's encoding.
            When provided and tiktoken supports encoding_for_model, that
            encoding will be used.

    Returns:
        str: The original text when it fits within `token_limit`, or a truncated
            version ending with "...[TRUNCATED]". The function always returns
            a string and swallows internal errors, returning a best-effort result.
    """
    sentinel = "...[TRUNCATED]"
    try:
        if text is None:
            return ""
        if not isinstance(text, str):
            try:
                text = str(text)
            except Exception:
                return ""
        try:
            tok_limit = int(token_limit)
        except Exception:
            tok_limit = 0

        if tok_limit <= 0:
            # Nothing allowed; return sentinel only (or empty)
            return sentinel

        # Try to use tiktoken if available
        try:
            import tiktoken  # type: ignore
            encoding = None
            # Prefer encoding_for_model when a model is provided
            if model and hasattr(tiktoken, "encoding_for_model"):
                try:
                    encoding = tiktoken.encoding_for_model(model)
                except Exception:
                    encoding = None
            if encoding is None:
                # Fall back to a common encoding name; this is safe for many models.
                try:
                    encoding = tiktoken.get_encoding("cl100k_base")
                except Exception:
                    encoding = None

            if encoding is not None:
                try:
                    tokens = encoding.encode(text)
                    if len(tokens) <= tok_limit:
                        return text
                    # Reserve a small number of tokens for the sentinel; use 3 as requested
                    take = max(0, tok_limit - 3)
                    truncated_tokens = tokens[:take]
                    try:
                        decoded = encoding.decode(truncated_tokens)
                        return decoded + sentinel
                    except Exception:
                        # If decode fails, fall back to best-effort string conversion
                        try:
                            partial_text = "".join(
                                chr(t % 0x110000) for t in truncated_tokens[:max(0, min(len(truncated_tokens), 1000))]
                            )
                            return partial_text + sentinel
                        except Exception:
                            return sentinel
                except Exception:
                    # Fall through to character-based fallback
                    pass
        except Exception:
            # tiktoken not available or failed to import; fall back below
            pass

        # Fallback: approximate char-based truncation using an average chars-per-token heuristic
        avg_chars_per_token = 4
        char_limit = tok_limit * avg_chars_per_token
        if len(text) <= char_limit:
            return text
        # Reserve space for sentinel
        take_chars = max(0, char_limit - len(sentinel))
        return text[:take_chars] + sentinel

    except Exception as e:
        logger.exception(f"truncate_to_token_limit failed: {e}")
        try:
            # As a final fallback, coerce to string and trim to a small size.
            txt = "" if text is None else str(text)
            return txt[:max(0, token_limit * 4)] + sentinel if txt else ""
        except Exception:
            return ""

def serialize_tool_output(result_or_error) -> str:
    """Serialize a tool function result or error into a string.

    This helper attempts to create a JSON representation of the provided
    result_or_error in a safe and portable manner. It falls back to str() or
    repr() when JSON serialization is not possible.

    Args:
        result_or_error: The value returned by a tool/function or an Exception.

    Returns:
        str: A stable string representation suitable for embedding in messages
             or storing alongside a function call record.
    """
    if result_or_error is None:
        return ""

    if isinstance(result_or_error, str):
        return result_or_error

    def _default(o):
        try:
            if hasattr(o, "to_dict") and callable(getattr(o, "to_dict")):
                return o.to_dict()
            if hasattr(o, "__dict__"):
                return {k: v for k, v in o.__dict__.items() if not k.startswith("_")}
            return repr(o)
        except Exception:
            return repr(o)

    try:
        return json.dumps(result_or_error, ensure_ascii=False, default=_default)
    except TypeError:
        # Try some common coercions
        try:
            if hasattr(result_or_error, "to_dict") and callable(getattr(result_or_error, "to_dict")):
                return json.dumps(result_or_error.to_dict(), ensure_ascii=False, default=_default)
            if hasattr(result_or_error, "__dict__"):
                return json.dumps({k: v for k, v in result_or_error.__dict__.items() if not k.startswith("_")}, ensure_ascii=False, default=_default)
        except Exception:
            # Fall through to best-effort string coercion
            pass
    except Exception:
        pass

    try:
        return str(result_or_error)
    except Exception:
        return repr(result_or_error)

def build_function_call_output_item(call_id: str, result_or_error, serialized_output: Optional[str] = None) -> Dict[str, Any]:
    """Build a standardized function_call_output item for a completed tool invocation.

    Args:
        call_id (str): The identifier for the function/tool call.
        result_or_error: The value returned by the function, or an Exception
            instance.
        serialized_output (Optional[str]): If provided, this pre-serialized string
            will be used as the "output" value in the returned item instead of
            calling serialize_tool_output on result_or_error. This is useful when
            callers already have a stable serialized representation and want to
            avoid double-serialization or custom truncation.

    Returns:
        Dict[str, Any]: A dictionary containing at least:
            - "call_id": call_id (preferred)
            - "id": call_id (legacy key, retained for compatibility)
            - "output": serialized string of the result or error
            - "error": optional boolean flag set to True when result_or_error
              is an Exception
            - "error_type": optional, the exception class name when an error
              occurred
            - "error_message": optional, the exception message when an error
              occurred
    """
    if serialized_output is not None:
        output_str = serialized_output
    else:
        output_str = serialize_tool_output(result_or_error)
    # Include both 'call_id' (preferred) and 'id' (legacy) for compatibility.
    item: Dict[str, Any] = {"call_id": call_id, "id": call_id, "output": output_str}

    if isinstance(result_or_error, Exception):
        try:
            item["error"] = True
            item["error_type"] = type(result_or_error).__name__
            item["error_message"] = str(result_or_error)
        except Exception:
            # Ensure we never raise from this helper
            logger.debug("build_function_call_output_item: failed to attach error metadata", exc_info=True)

    return item

def build_summarization_followup_params(
    prev_response_id: Optional[str],
    function_call_outputs: List[Dict[str, Any]],
    summary_instruction: str,
    model: str,
    max_output_tokens: int,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Construct parameters for a summarization follow-up request.

    This helper packages previous function call outputs and a human instruction
    into a compact param set suitable for invoking a summarization or
    aggregation model call. It performs light validation and ensures stable
    shapes for downstream callers.

    Args:
        prev_response_id (Optional[str]): Identifier of the previous response to reference.
        function_call_outputs (List[Dict[str, Any]]): List of function call output items,
            typically created by build_function_call_output_item.
        summary_instruction (str): Instruction text guiding the summarization.
        model (str): The model name to use for the summarization step.
        max_output_tokens (int): Maximum number of tokens to allow for summarization output.
        tools (Optional[List[Dict[str, Any]]]): Optional tool descriptors that may assist the model.

    Returns:
        Dict[str, Any]: A parameter dictionary ready to be passed to a Responses/Completions API
                        or to the internal orchestration layer.
    """
    # Defensive copies/coercions
    fc_outputs = function_call_outputs or []
    try:
        # Ensure each output is a dict with expected keys
        sanitized_outputs: List[Dict[str, Any]] = []
        for idx, item in enumerate(fc_outputs):
            if not isinstance(item, dict):
                logger.debug(f"build_summarization_followup_params: coercing non-dict output at index {idx}")
                # Attempt to coerce simple tuples or sequences
                try:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        coerced = {"id": item[0], "output": serialize_tool_output(item[1])}
                        sanitized_outputs.append(coerced)
                        continue
                except Exception:
                    pass
                # Fallback: stringify the item
                sanitized_outputs.append({"id": getattr(item, "id", f"item_{idx}"), "output": serialize_tool_output(item)})
                continue
            sanitized_outputs.append(item)
    except Exception:
        logger.exception("build_summarization_followup_params: failed to sanitize function_call_outputs; using originals")
        sanitized_outputs = fc_outputs

    params: Dict[str, Any] = {
        "parent_response_id": prev_response_id,
        "summary_instruction": summary_instruction,
        "model": model,
        "max_output_tokens": int(max_output_tokens) if max_output_tokens is not None else None,
        "function_call_outputs": sanitized_outputs,
    }

    if tools:
        params["tools"] = tools

    # Optionally include some lightweight metadata to aid debugging/telemetry
    try:
        params["_meta"] = {
            "source": "summarization_followup",
            "tool_count": len(sanitized_outputs),
            "model_normalized": strip_openai_prefix(model) if isinstance(model, str) else model,
        }
    except Exception:
        # Non-critical; swallow errors
        pass

    return params
