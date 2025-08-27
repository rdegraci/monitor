import logging
import json
from openai import OpenAI

from monitor import config
from monitor.core.tools import TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS
from monitor.core.tooling import execute_tool_call
from monitor.lib.message_utils import normalize_message, sanitize_messages
from monitor.lib.token_management import count_message_tokens, update_token_usage
from monitor.lib import rate_limiter
from monitor.lib.llm_utils import dict_to_attr, validate_tool_message_order
from monitor.lib.tool_loading import function_descriptions

logger = logging.getLogger(__name__)

client = None

# Constants
OPENAI_PREFIX = "openai/"
DEFAULT_TOOL_TYPE = "function"
PARAMETERS_TYPE_OBJECT = "object"
FUNCTION_CALL_TYPE = "function_call"
TOOL_CALL_TYPE = "tool_call"
FUNCTION_TOOL_CALL_TYPES = (FUNCTION_CALL_TYPE, TOOL_CALL_TYPE)
FUNCTION_CALL_OUTPUT_TYPE = "function_call_output"
REQUEST_PARAM_MODEL = "model"
REQUEST_PARAM_INPUT = "input"
REQUEST_PREV_RESPONSE_ID = "previous_response_id"
REQUEST_PARAM_TOOLS = "tools"
REQUEST_PARAM_TOOL_CHOICE = "tool_choice"
REQUEST_PARAM_TEMPERATURE = "temperature"
REQUEST_PARAM_TOP_P = "top_p"
REQUEST_PARAM_FREQUENCY_PENALTY = "frequency_penalty"
REQUEST_PARAM_PRESENCE_PENALTY = "presence_penalty"
REQUEST_PARAM_MAX_OUTPUT_TOKENS = "max_output_tokens"
USER_ROLE = "user"
SYSTEM_ROLE = "system"
CONTENT_KEY = "content"
ROLE_KEY = "role"
CHOICES_KEY = "choices"
MESSAGE_KEY = "message"
OUTPUT_KEY = "output"
OUTPUT_TEXT_ATTR = "output_text"
ID_KEY = "id"
USAGE_KEYS = ("total_tokens", "total_token_count", "total")
MAX_FUNCTION_CALL_ITERATIONS = 25
SUMMARY_MAX_OUTPUT_TOKENS = 300
MAX_ERROR_INPUT_SNIPPET = 100
PARAMETERS_PROPERTIES_KEY = "properties"
PARAMETERS_REQUIRED_KEY = "required"
TYPE_KEY = "type"
NAME_KEY = "name"
DESCRIPTION_KEY = "description"
ARGUMENTS_KEY = "arguments"
ARGS_KEY = "args"
TOOL_NAME_KEYS = ("tool", "tool_name")
CALL_ID_KEYS = ("call_id", "id")
SERIALIZATION_FAILED_STR = '{"error": "serialization_failed"}'
TEXT_KEY = "text"
MESSAGE_CONTENT_LIST_ITEM_KEYS = ("content", "text", "message")


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


def configure_responses_adapter():
    global client
    client = OpenAI()


def validate_responses_config():
    """Validate that required responses API configuration is present."""
    required_configs = ["MODEL", "RESPONSES_API"]
    missing_configs = []

    for config_name in required_configs:
        if not hasattr(config, config_name) or not getattr(config, config_name):
            missing_configs.append(config_name)

    if missing_configs:
        raise ValueError(
            f"Missing required responses API configuration: {missing_configs}"
        )

    logger.debug("Responses API configuration validated successfully")


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


def get_tools_for_model():
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
            tools = GEMINI_TOOL_DESCRIPTIONS
            logger.debug(
                f"Using Gemini tool descriptions ({len(tools) if tools else 0} tools)"
            )
        else:
            tools = function_descriptions(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, model_lower)
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


def call_responses_api(messages):
    """Make the actual call to the responses API via OpenAI Responses API.

    Args:
        messages (list): Prepared messages for the API

    Returns:
        dict: Normalized response wrapper suitable for convert_response_format

    Raises:
        Exception: Any API-related errors
    """
    try:
        logger.debug("Calling responses API via OpenAI client")

        # Get tools for the current model
        tools, tool_choice = get_tools_for_model()

        # Build request parameters, include only non-None values
        params = {REQUEST_PARAM_MODEL: strip_openai_prefix(config.MODEL)}

        # Determine input: if a previous response id exists, send only the new user input
        if hasattr(config, "RESPONSE_ID") and getattr(config, "RESPONSE_ID"):
            params[REQUEST_PREV_RESPONSE_ID] = getattr(config, "RESPONSE_ID")
            # Extract most recent user message content
            user_text = None
            try:
                for m in reversed(messages):
                    if isinstance(m, dict) and m.get(ROLE_KEY) == USER_ROLE:
                        user_text = m.get(CONTENT_KEY)
                        break
            except Exception:
                user_text = None
            if not user_text:
                # Fallback: concatenate all message contents
                try:
                    user_text = " ".join(
                        m.get(CONTENT_KEY, "") for m in messages if isinstance(m, dict)
                    )
                except Exception:
                    user_text = ""
            params[REQUEST_PARAM_INPUT] = user_text
            logger.debug(
                "Sending only the new user input alongside previous_response_id to OpenAI Responses API"
            )
        else:
            # First-call: send prepared messages as input (may include system preferences)
            params[REQUEST_PARAM_INPUT] = messages
            logger.debug("Sending prepared messages as input to OpenAI Responses API")

        # Add optional parameters only if present in config
        if getattr(config, "TEMPERATURE", None) is not None:
            params[REQUEST_PARAM_TEMPERATURE] = getattr(config, "TEMPERATURE")
        if getattr(config, "TOP_P", None) is not None:
            params[REQUEST_PARAM_TOP_P] = getattr(config, "TOP_P")
        if getattr(config, "FREQUENCY_PENALTY", None) is not None:
            params[REQUEST_PARAM_FREQUENCY_PENALTY] = getattr(config, "FREQUENCY_PENALTY")
        if getattr(config, "PRESENCE_PENALTY", None) is not None:
            params[REQUEST_PARAM_PRESENCE_PENALTY] = getattr(config, "PRESENCE_PENALTY")

        max_output_tokens = getattr(config, "MAX_COMPLETION_TOKENS", None)
        if max_output_tokens is not None:
            params[REQUEST_PARAM_MAX_OUTPUT_TOKENS] = max_output_tokens

        # Add tools if available
        if tools:
            params[REQUEST_PARAM_TOOLS] = tools
            params[REQUEST_PARAM_TOOL_CHOICE] = tool_choice
            logger.debug(
                f"Added {len(tools)} tools to responses API call with choice '{tool_choice}'"
            )
        else:
            logger.debug("No tools available for responses API call")

        # Call OpenAI Responses API (initial call)
        response = client.responses.create(**params)

        logger.debug("Successfully received response from OpenAI Responses API")

        # Persist response id into config if present
        try:
            resp_id = getattr(response, ID_KEY, None)
            if resp_id:
                setattr(config, "RESPONSE_ID", resp_id)
                logger.debug(f"Persisted response id {resp_id} into config.RESPONSE_ID")
        except Exception:
            logger.debug("Failed to persist response id to config, continuing")

        # Extract token usage (support common shapes) for the initial response
        actual_tokens = None
        try:
            usage = getattr(response, "usage", None)
            if usage is None:
                actual_tokens = None
            else:
                # usage might be an object with attributes or a dict-like
                if isinstance(usage, dict):
                    actual_tokens = (
                        usage.get(USAGE_KEYS[0])
                        or usage.get(USAGE_KEYS[1])
                        or usage.get(USAGE_KEYS[2])
                    )
                else:
                    actual_tokens = (
                        getattr(usage, USAGE_KEYS[0], None)
                        or getattr(usage, USAGE_KEYS[1], None)
                        or getattr(usage, USAGE_KEYS[2], None)
                    )
        except Exception:
            actual_tokens = None

        # If actual_tokens is None, set to 0 to avoid None propagation
        if actual_tokens is None:
            actual_tokens = 0

        # Update token usage and rate limiter immediately for the initial response
        try:
            update_token_usage(actual_tokens)
            logger.debug(
                f"Updated token usage with {actual_tokens} tokens from OpenAI response"
            )
        except Exception:
            logger.exception("Failed to update token usage after OpenAI response")

        try:
            if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
                rate_limiter.RATE_LIMITER.add_request(actual_tokens)
                logger.debug(
                    f"Added request of {actual_tokens} tokens to rate limiter"
                )
        except Exception:
            logger.exception("Failed to add request to rate limiter after OpenAI response")

        # Begin function/tool call handling loop (up to max iterations)
        last_response = response
        max_iterations = MAX_FUNCTION_CALL_ITERATIONS
        iteration = 0
        last_iteration_had_calls = False
        while iteration < max_iterations:
            iteration += 1
            logger.debug(f"Function call handling iteration {iteration}")

            # Try to extract output items from last_response
            try:
                output = getattr(last_response, OUTPUT_KEY, None)
                if output is None:
                    try:
                        output = last_response.get(OUTPUT_KEY)  # type: ignore
                    except Exception:
                        output = None
            except Exception:
                output = None

            function_call_items = []

            # If output is a list, scan for function/tool calls
            if isinstance(output, list):
                for item in output:
                    try:
                        item_type = None
                        if hasattr(item, TYPE_KEY):
                            item_type = getattr(item, TYPE_KEY, None)
                        elif isinstance(item, dict):
                            item_type = item.get(TYPE_KEY)

                        # Normalize to string if possible
                        if item_type:
                            item_type_str = str(item_type).lower()
                        else:
                            item_type_str = None

                        if item_type_str in (FUNCTION_CALL_TYPE, TOOL_CALL_TYPE):
                            logger.debug(
                                f"Detected function/tool call item with type '{item_type_str}'"
                            )

                            # Extract call id
                            call_id = None
                            if hasattr(item, CALL_ID_KEYS[0]):
                                call_id = getattr(item, CALL_ID_KEYS[0], None)
                            elif hasattr(item, CALL_ID_KEYS[1]):
                                call_id = getattr(item, CALL_ID_KEYS[1], None)
                            elif isinstance(item, dict):
                                call_id = item.get(CALL_ID_KEYS[0]) or item.get(CALL_ID_KEYS[1])

                            # Extract function/tool name
                            name = None
                            if hasattr(item, NAME_KEY):
                                name = getattr(item, NAME_KEY, None)
                            elif isinstance(item, dict):
                                name = item.get(NAME_KEY)

                            # Sometimes the tool name might be under 'tool' or 'tool_name'
                            if not name and isinstance(item, dict):
                                for tk in TOOL_NAME_KEYS:
                                    if tk in item:
                                        name = item.get(tk)
                                        break
                            if not name and hasattr(item, TOOL_NAME_KEYS[0]):
                                name = getattr(item, TOOL_NAME_KEYS[0], None)

                            # Extract arguments; can be dict, object, or JSON string
                            arguments = None
                            if hasattr(item, ARGUMENTS_KEY):
                                try:
                                    arguments = getattr(item, ARGUMENTS_KEY, None)
                                except Exception:
                                    arguments = None
                            elif isinstance(item, dict):
                                arguments = (
                                    item.get(ARGUMENTS_KEY)
                                    or item.get(CONTENT_KEY)
                                    or item.get(ARGS_KEY)
                                )

                            # If arguments is a string, attempt to parse JSON
                            if isinstance(arguments, str):
                                try:
                                    parsed_args = json.loads(arguments)
                                    arguments = parsed_args
                                except Exception:
                                    # keep as string if not JSON
                                    pass

                            # Build normalized function call item
                            function_call_items.append(
                                {
                                    "call_id": call_id,
                                    "name": name,
                                    "arguments": arguments,
                                    "raw_item": item,
                                }
                            )
                    except Exception:
                        logger.exception(
                            "Error while scanning output items for function calls"
                        )

            # Track whether this iteration had any function/tool calls
            last_iteration_had_calls = bool(function_call_items)

            # If no function calls detected, break the loop
            if not function_call_items:
                logger.debug(
                    "No function/tool call items detected in response output; exiting function call loop"
                )
                break

            # Execute each detected function call
            function_call_outputs = []
            for fc in function_call_items:
                call_id = fc.get("call_id")
                name = fc.get("name")
                arguments = fc.get("arguments")

                logger.debug(
                    f"Preparing to execute tool/function '{name}' with call_id '{call_id}' and arguments: {arguments}"
                )

                tool_call = {
                    "function": {"name": name, "arguments": arguments},
                    "id": call_id,
                }

                try:
                    result, error = execute_tool_call(tool_call)
                    if error:
                        logger.error(
                            f"Error executing tool/function '{name}' (call_id: {call_id}): {error}"
                        )
                        result_or_error = {"error": str(error)}
                    else:
                        logger.debug(
                            f"Executed tool/function '{name}' (call_id: {call_id}) successfully"
                        )
                        result_or_error = result if result is not None else {}
                except Exception as e:
                    logger.exception(
                        f"Exception executing tool/function '{name}' (call_id: {call_id})"
                    )
                    result_or_error = {"error": str(e)}

                try:
                    output_payload = json.dumps(result_or_error)
                except Exception:
                    try:
                        output_payload = json.dumps(
                            {"error": "Unable to serialize tool result"}
                        )
                    except Exception:
                        output_payload = SERIALIZATION_FAILED_STR

                function_call_outputs.append(
                    {
                        TYPE_KEY: FUNCTION_CALL_OUTPUT_TYPE,
                        "call_id": call_id,
                        "output": output_payload,
                    }
                )

            # If we have outputs from executing tools, send them back as a follow-up response
            if function_call_outputs:
                try:
                    followup_params = {REQUEST_PARAM_MODEL: strip_openai_prefix(config.MODEL)}
                    # Ensure previous_response_id is the last persisted response id
                    if hasattr(config, "RESPONSE_ID") and getattr(config, "RESPONSE_ID"):
                        followup_params[REQUEST_PREV_RESPONSE_ID] = getattr(config, "RESPONSE_ID")
                    followup_params[REQUEST_PARAM_INPUT] = function_call_outputs

                    # Preserve optional params
                    if getattr(config, "TEMPERATURE", None) is not None:
                        followup_params[REQUEST_PARAM_TEMPERATURE] = getattr(config, "TEMPERATURE")
                    if getattr(config, "TOP_P", None) is not None:
                        followup_params[REQUEST_PARAM_TOP_P] = getattr(config, "TOP_P")
                    if getattr(config, "FREQUENCY_PENALTY", None) is not None:
                        followup_params[REQUEST_PARAM_FREQUENCY_PENALTY] = getattr(
                            config, "FREQUENCY_PENALTY"
                        )
                    if getattr(config, "PRESENCE_PENALTY", None) is not None:
                        followup_params[REQUEST_PARAM_PRESENCE_PENALTY] = getattr(
                            config, "PRESENCE_PENALTY"
                        )
                    if max_output_tokens is not None:
                        followup_params[REQUEST_PARAM_MAX_OUTPUT_TOKENS] = max_output_tokens

                    # Add tools if available
                    if tools:
                        followup_params[REQUEST_PARAM_TOOLS] = tools
                        followup_params[REQUEST_PARAM_TOOL_CHOICE] = tool_choice

                    logger.debug(
                        f"Sending follow-up responses.create with {len(function_call_outputs)} function_call_output items"
                    )
                    followup_response = client.responses.create(**followup_params)

                    logger.debug("Received follow-up response from OpenAI Responses API")

                    # Persist follow-up response id
                    try:
                        follow_id = getattr(followup_response, ID_KEY, None)
                        if follow_id:
                            setattr(config, "RESPONSE_ID", follow_id)
                            logger.debug(
                                f"Persisted follow-up response id {follow_id} into config.RESPONSE_ID"
                            )
                    except Exception:
                        logger.debug("Failed to persist follow-up response id to config, continuing")

                    # Extract token usage for follow-up response
                    follow_tokens = None
                    try:
                        usage = getattr(followup_response, "usage", None)
                        if usage is None:
                            follow_tokens = None
                        else:
                            if isinstance(usage, dict):
                                follow_tokens = (
                                    usage.get(USAGE_KEYS[0])
                                    or usage.get(USAGE_KEYS[1])
                                    or usage.get(USAGE_KEYS[2])
                                )
                            else:
                                follow_tokens = (
                                    getattr(usage, USAGE_KEYS[0], None)
                                    or getattr(usage, USAGE_KEYS[1], None)
                                    or getattr(usage, USAGE_KEYS[2], None)
                                )
                    except Exception:
                        follow_tokens = None

                    if follow_tokens is None:
                        follow_tokens = 0

                    # Update token usage and rate limiter for follow-up
                    try:
                        update_token_usage(follow_tokens)
                        logger.debug(
                            f"Updated token usage with {follow_tokens} tokens from follow-up OpenAI response"
                        )
                    except Exception:
                        logger.exception(
                            "Failed to update token usage after follow-up OpenAI response"
                        )

                    try:
                        if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
                            rate_limiter.RATE_LIMITER.add_request(follow_tokens)
                            logger.debug(
                                f"Added follow-up request of {follow_tokens} tokens to rate limiter"
                            )
                    except Exception:
                        logger.exception(
                            "Failed to add follow-up request to rate limiter after OpenAI response"
                        )

                    # Safely add follow_tokens to actual_tokens so total token accounting includes the follow-up
                    try:
                        if actual_tokens is None:
                            actual_tokens = 0
                        try:
                            # Attempt numeric addition; coerce to int if possible
                            if isinstance(follow_tokens, (int, float)):
                                actual_tokens += int(follow_tokens)
                                logger.debug(
                                    f"Added {follow_tokens} follow-up tokens to actual_tokens, new total: {actual_tokens}"
                                )
                            else:
                                # Try to coerce strings that represent integers
                                if isinstance(follow_tokens, str) and follow_tokens.isdigit():
                                    actual_tokens += int(follow_tokens)
                                    logger.debug(
                                        f"Coerced and added follow-up tokens '{follow_tokens}' to actual_tokens, new total: {actual_tokens}"
                                    )
                                else:
                                    logger.debug(
                                        f"Follow-up tokens value not numeric, skipping addition to actual_tokens: {follow_tokens}"
                                    )
                        except Exception:
                            logger.exception("Failed while attempting to coerce and add follow_tokens to actual_tokens")
                    except Exception:
                        logger.exception("Failed to add follow_tokens to actual_tokens")

                    # Set last_response to followup_response and continue loop
                    last_response = followup_response
                except Exception as e:
                    logger.exception(
                        "Failed to send follow-up responses.create for function call outputs"
                    )
                    # If follow-up fails, break to avoid infinite loop
                    break
            else:
                # No outputs to send back; break loop
                break

        # If we reached the max iteration limit and the last iteration had function/tool calls,
        # attempt to send a summarization follow-up to avoid truncation of tool call results.
        try:
            if (
                iteration >= max_iterations
                and last_iteration_had_calls
            ):
                if client is None:
                    logger.debug("Skipping summarization follow-up because client is not configured")
                elif not (hasattr(config, "RESPONSE_ID") and getattr(config, "RESPONSE_ID")):
                    logger.debug("Skipping summarization follow-up because no config.RESPONSE_ID is present")
                else:
                    try:
                        summary_instruction = (
                            "Please summarize the previous response and the results of the function/tool calls into a concise summary."
                        )
                        summary_params = {
                            REQUEST_PARAM_MODEL: strip_openai_prefix(config.MODEL),
                            REQUEST_PREV_RESPONSE_ID: getattr(config, "RESPONSE_ID"),
                            REQUEST_PARAM_INPUT: summary_instruction,
                        }
                        # Set a conservative max output tokens for the summary
                        summary_params[REQUEST_PARAM_MAX_OUTPUT_TOKENS] = SUMMARY_MAX_OUTPUT_TOKENS

                        logger.debug("Sending summarization follow-up due to function call iteration truncation")
                        summary_response = client.responses.create(**summary_params)
                        logger.debug("Received summarization follow-up response from OpenAI Responses API")

                        # Persist summary response id
                        try:
                            summary_id = getattr(summary_response, ID_KEY, None)
                            if summary_id:
                                setattr(config, "RESPONSE_ID", summary_id)
                                logger.debug(
                                    f"Persisted summarization response id {summary_id} into config.RESPONSE_ID"
                                )
                        except Exception:
                            logger.debug("Failed to persist summarization response id to config, continuing")

                        # Extract token usage for summary response
                        summary_tokens = None
                        try:
                            usage = getattr(summary_response, "usage", None)
                            if usage is None:
                                summary_tokens = None
                            else:
                                if isinstance(usage, dict):
                                    summary_tokens = (
                                        usage.get(USAGE_KEYS[0])
                                        or usage.get(USAGE_KEYS[1])
                                        or usage.get(USAGE_KEYS[2])
                                    )
                                else:
                                    summary_tokens = (
                                        getattr(usage, USAGE_KEYS[0], None)
                                        or getattr(usage, USAGE_KEYS[1], None)
                                        or getattr(usage, USAGE_KEYS[2], None)
                                    )
                        except Exception:
                            summary_tokens = None

                        if summary_tokens is None:
                            summary_tokens = 0

                        # Update token usage and rate limiter for summary
                        try:
                            update_token_usage(summary_tokens)
                            logger.debug(
                                f"Updated token usage with {summary_tokens} tokens from summarization OpenAI response"
                            )
                        except Exception:
                            logger.exception(
                                "Failed to update token usage after summarization OpenAI response"
                            )

                        try:
                            if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
                                rate_limiter.RATE_LIMITER.add_request(summary_tokens)
                                logger.debug(
                                    f"Added summarization request of {summary_tokens} tokens to rate limiter"
                                )
                        except Exception:
                            logger.exception(
                                "Failed to add summarization request to rate limiter after OpenAI response"
                            )

                        # Safely add summary_tokens to actual_tokens so total token accounting includes the summary follow-up
                        try:
                            if actual_tokens is None:
                                actual_tokens = 0
                            try:
                                # Attempt numeric addition; coerce to int if possible
                                if isinstance(summary_tokens, (int, float)):
                                    actual_tokens += int(summary_tokens)
                                    logger.debug(
                                        f"Added {summary_tokens} summary tokens to actual_tokens, new total: {actual_tokens}"
                                    )
                                else:
                                    # Try to coerce strings that represent integers
                                    if isinstance(summary_tokens, str) and summary_tokens.isdigit():
                                        actual_tokens += int(summary_tokens)
                                        logger.debug(
                                            f"Coerced and added summary tokens '{summary_tokens}' to actual_tokens, new total: {actual_tokens}"
                                        )
                                    else:
                                        logger.debug(
                                            f"Summary tokens value not numeric, skipping addition to actual_tokens: {summary_tokens}"
                                        )
                            except Exception:
                                logger.exception("Failed while attempting to coerce and add summary_tokens to actual_tokens")
                        except Exception:
                            logger.exception("Failed to add summary_tokens to actual_tokens")

                        # Replace last_response with the summary response so normalization returns the summary
                        last_response = summary_response
                    except Exception:
                        logger.exception("Failed to send or process summarization follow-up; proceeding without summary")
        except Exception:
            # Any unexpected error in summarization handling should not prevent normal flow
            logger.exception("Unexpected error while attempting summarization follow-up")

        # After loop finishes, normalize the last_response into wrapper as before
        output_text = ""
        try:
            # Prefer output_text if present
            if hasattr(last_response, OUTPUT_TEXT_ATTR) and getattr(last_response, OUTPUT_TEXT_ATTR):
                output_text = getattr(last_response, OUTPUT_TEXT_ATTR)
            else:
                # Attempt to extract from response.output which may be a list of items
                output = getattr(last_response, OUTPUT_KEY, None)
                if output is None:
                    # Some SDKs might store textual output under 'choices' or other shapes
                    # Try to read last_response.get('output') if possible
                    try:
                        output = last_response.get(OUTPUT_KEY)  # type: ignore
                    except Exception:
                        output = None
                if isinstance(output, str):
                    output_text = output
                elif isinstance(output, list):
                    parts = []
                    for item in output:
                        if item is None:
                            continue
                        if isinstance(item, str):
                            parts.append(item)
                        elif isinstance(item, dict):
                            # common key names: 'content', 'text', 'message'
                            if CONTENT_KEY in item:
                                content = item[CONTENT_KEY]
                                if isinstance(content, list):
                                    # list of dicts or strings
                                    for sub in content:
                                        if isinstance(sub, str):
                                            parts.append(sub)
                                        elif isinstance(sub, dict):
                                            # nested content may have 'text' or 'content'
                                            parts.append(sub.get(TEXT_KEY) or sub.get(CONTENT_KEY) or "")
                                elif isinstance(content, str):
                                    parts.append(content)
                            elif TEXT_KEY in item:
                                parts.append(item.get(TEXT_KEY) or "")
                            elif MESSAGE_KEY in item and isinstance(item.get(MESSAGE_KEY), dict):
                                msg = item.get(MESSAGE_KEY)
                                # message may contain 'content' as string or list
                                if isinstance(msg.get(CONTENT_KEY), str):
                                    parts.append(msg.get(CONTENT_KEY))
                                elif isinstance(msg.get(CONTENT_KEY), list):
                                    for sub in msg.get(CONTENT_KEY):
                                        if isinstance(sub, str):
                                            parts.append(sub)
                                        elif isinstance(sub, dict):
                                            parts.append(sub.get(TEXT_KEY) or sub.get(CONTENT_KEY) or "")
                        else:
                            # Fallback string conversion
                            try:
                                parts.append(str(item))
                            except Exception:
                                pass
                    output_text = "".join(parts)
                elif isinstance(output, dict):
                    # Try common keys
                    if CONTENT_KEY in output:
                        c = output[CONTENT_KEY]
                        if isinstance(c, str):
                            output_text = c
                        elif isinstance(c, list):
                            output_text = "".join(
                                x if isinstance(x, str) else x.get(TEXT_KEY, "") for x in c
                            )
                    else:
                        # Try converting to string representation
                        try:
                            output_text = str(output)
                        except Exception:
                            output_text = ""
                else:
                    output_text = ""
        except Exception:
            output_text = ""

        # Build normalized wrapper expected by the rest of the system using last_response
        wrapper = {
            ID_KEY: getattr(last_response, ID_KEY, None),
            CHOICES_KEY: [{MESSAGE_KEY: {CONTENT_KEY: output_text}}],
            "usage": {USAGE_KEYS[0]: actual_tokens},
        }

        logger.debug("Normalized OpenAI response into internal wrapper format")
        return wrapper

    except Exception as e:
        logger.error(f"Responses API call failed: {e}", exc_info=True)
        raise


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


def handle_response_errors(error, user_input=None):
    """Handle responses API specific errors with appropriate logging.

    Args:
        error (Exception): The error that occurred
        user_input (str, optional): The original user input for context

    Returns:
        tuple: (None, error_message) following llm.py error format
    """
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


def response_completion(user_input, log_prefix="", error_message="Error during responses API completion"):
    """Main entry point for responses API completion.

    This function handles the complete flow for responses API:
    1. Validates configuration
    2. Prepares messages
    3. Estimates tokens
    4. Validates messages
    5. Calls responses API
    6. Processes response
    7. Updates token usage

    Args:
        user_input (str): The user's input/query
        log_prefix (str): Prefix for log messages
        error_message (str): Default error message

    Returns:
        tuple: (response, error_message) where response is None on error
    """
    try:
        logger.debug(f"{log_prefix} Starting responses API completion")

        # Validate configuration
        validate_responses_config()

        # Prepare messages for responses API
        messages = prepare_response_messages(user_input)

        # Estimate token count
        estimated_tokens = estimate_response_tokens(messages)

        # Validate message order
        try:
            validate_tool_message_order(messages)
        except ValueError as ve:
            logger.error(f"Message validation failed for responses API: {ve}")
            return None, str(ve)

        # Check if we're within token limits
        if hasattr(config, "MODEL_MAX_TPM") and estimated_tokens > config.MODEL_MAX_TPM:
            error_msg = (
                f"Input too large: {estimated_tokens} tokens "
                f"vs model limit {config.MODEL_MAX_TPM}. Cannot send request to responses API. "
                "Please reduce the size of your input."
            )
            logger.error(error_msg)
            return None, error_msg

        # Apply rate limiting if configured
        if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
            wait_result = rate_limiter.RATE_LIMITER.wait_if_needed(estimated_tokens)
            if wait_result is None:
                error_msg = (
                    f"Rate limit safety threshold exceeded: {estimated_tokens} tokens. "
                    f"Model limit {getattr(config, 'MODEL_MAX_TPM', 'unknown')} tokens. "
                    "Reduce the size of your request."
                )
                logger.error(error_msg)
                return None, error_msg

        # Call responses API
        api_response = call_responses_api(messages)

        # Convert response format
        response = convert_response_format(api_response)

        logger.debug(f"{log_prefix} Successfully completed responses API request")
        return response, None

    except Exception as e:
        return handle_response_errors(e, user_input)


def get_response_initial_completion(user_input):
    """Get initial response from responses API for the query.

    Args:
        user_input (str): The user's input/query

    Returns:
        tuple: (response, error_message) where response is None on error
    """
    logger.debug("Getting initial responses API response...")
    return response_completion(
        user_input,
        log_prefix="Initial responses API request:",
        error_message="I apologize, but I encountered an error processing your request via responses API. Please try again",
    )
