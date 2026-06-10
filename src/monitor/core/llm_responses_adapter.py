import logging
import json
import threading
import signal
import uuid
from openai import OpenAI

from monitor import config
from monitor.core.tooling import execute_tool_call
from monitor.lib.message_utils import normalize_message, sanitize_messages
from monitor.lib.token_management import count_message_tokens, update_token_usage, token_budgeter
from monitor.lib import rate_limiter
from monitor.lib.llm_utils import (
    dict_to_attr, 
    validate_tool_message_order, 
    strip_openai_prefix,
    prepare_response_messages,
    estimate_response_tokens,
    get_tools_for_model,
    convert_response_format,
    handle_response_errors,
    build_function_call_output_item,
    serialize_tool_output,
    build_summarization_followup_params,
    truncate_to_token_limit,
    )
from monitor.lib.tool_loading import function_descriptions
from monitor.lib.progress import progress_dots
from monitor.lib.llm_utils import is_reasoning_model

logger = logging.getLogger(__name__)

client = None

# Constants
TYPE_KEY = "type"
NAME_KEY = "name"
DESCRIPTION_KEY = "description"
DEFAULT_TOOL_TYPE = "function"
PARAMETERS_PROPERTIES_KEY = "properties"
PARAMETERS_REQUIRED_KEY = "required"
PARAMETERS_TYPE_OBJECT = "object"

ROLE_KEY = "role"
SYSTEM_ROLE = "system"
CONTENT_KEY = "content"
USER_ROLE = "user"

CHOICES_KEY = "choices"
MESSAGE_KEY = "message"

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
OUTPUT_KEY = "output"
OUTPUT_TEXT_ATTR = "output_text"
ID_KEY = "id"
USAGE_KEYS = ("total_tokens", "total_token_count", "total")
ARGUMENTS_KEY = "arguments"
ARGS_KEY = "args"
TOOL_NAME_KEYS = ("tool", "tool_name")
CALL_ID_KEYS = ("call_id", "id")
SERIALIZATION_FAILED_STR = '{"error": "serialization_failed"}'
TEXT_KEY = "text"
MESSAGE_CONTENT_LIST_ITEM_KEYS = ("content", "text", "message")

# WARNING: Larger iterations count can increase costs, runtime, and 
# risk of runaway function-call loops, but allow the LLM to be more agentic
MAX_FUNCTION_CALL_ITERATIONS = 256
SUMMARY_MAX_OUTPUT_TOKENS = 2048

# Safety margin applied to input_window before deciding whether a request
# fits the model's context. `count_message_tokens` undercounts by 10-30% on
# Responses API payloads because it doesn't see server-side cached context
# (chained via previous_response_id), tool definitions, or the wrapping
# overhead on `function_call_output` items. We budget against a slightly
# smaller window so an undercounted estimate that "fits" doesn't trip an
# OpenAI 400 context_length_exceeded on the wire. 0.85 catches most
# undercounts; lower it further if 400s persist on your traffic.
INPUT_WINDOW_SAFETY_RATIO = 0.85

def configure_responses_adapter():
    """Configure the OpenAI client for Responses API usage."""
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

def _cancellable_responses_create(create_callable, params, progress_label=None):
    """Execute OpenAI Responses API call in a background thread, allowing Ctrl-C to cancel.

    This helper starts the provided create_callable(**params) in a daemon thread and
    temporarily sets the SIGINT handler to the default KeyboardInterrupt-raising handler
    while waiting. If the user presses Ctrl-C, a KeyboardInterrupt will be raised,
    allowing callers to handle cancellation (e.g., return control to the caller).

    Args:
        create_callable: Callable to invoke (typically client.responses.create).
        params (dict): Parameters to pass to the callable.
        progress_label (str | None): Optional label to display with progress_dots.

    Returns:
        Any: The result returned by the callable on success.

    Raises:
        KeyboardInterrupt: If the user cancels with Ctrl-C during the wait.
        Exception: Any error raised by the callable is propagated.
    """
    result_container = {"result": None, "error": None}

    def target():
        try:
            result_container["result"] = create_callable(**params)
        except Exception as e:
            result_container["error"] = e

    thread = threading.Thread(target=target, name="OpenAIResponsesCreate", daemon=True)

    # Save and set SIGINT handler to default to ensure Ctrl-C raises KeyboardInterrupt
    prev_handler = None
    try:
        try:
            prev_handler = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, signal.default_int_handler)
        except Exception:
            # If not in the main thread or setting signal fails, continue without changing handler
            prev_handler = None

        # Start the worker thread only after setting the temporary SIGINT handler
        thread.start()

        # Use progress dots while waiting
        ctx = progress_dots(progress_label) if progress_label is not None else progress_dots()
        with ctx:
            while thread.is_alive():
                thread.join(0.1)
        if result_container["error"] is not None:
            raise result_container["error"]
        return result_container["result"]
    finally:
        # Restore original SIGINT handler
        if prev_handler is not None:
            try:
                signal.signal(signal.SIGINT, prev_handler)
            except Exception:
                pass

def call_responses_api(messages, tool_descriptions, gemini_tool_descriptions, request_id=None):
    """Make the actual call to the OpenAI Responses API.

    This method supports cancellable behavior: pressing Ctrl-C during any Responses API call
    will raise KeyboardInterrupt, allowing the caller to handle cancellation (e.g., by returning
    (None, "Cancelled by user")).

    Args:
        messages (list): Prepared messages for the API
        tool_descriptions (list): Available tool specifications for the current model
        gemini_tool_descriptions (list): Alternative tool specifications (for Gemini models)

    Returns:
        dict: Normalized response wrapper suitable for convert_response_format

    Raises:
        Exception: Any API-related errors (KeyboardInterrupt will propagate for cancellation)
    """
    try:
        logger.debug("Calling responses API via OpenAI client")

        # Lazy initialize client if not already configured
        if client is None:
            try:
                configure_responses_adapter()
                logger.debug("Configured responses adapter (OpenAI client) lazily")
            except Exception:
                logger.exception("Failed to configure responses adapter lazily")
            if client is None:
                logger.error("Responses client could not be configured. Please call configure_responses_adapter() or verify your OpenAI API credentials.")
                raise RuntimeError("Responses client could not be configured. Please call configure_responses_adapter() or verify your OpenAI API credentials.")

        # Get tools for the current model
        tools, tool_choice = get_tools_for_model(tool_descriptions, gemini_tool_descriptions)

        # Build request parameters, include only non-None values
        params = {REQUEST_PARAM_MODEL: strip_openai_prefix(config.MODEL)}

        # Determine if the current model is a reasoning model to force temperature=1
        reasoning_model = False
        try:
            reasoning_model = is_reasoning_model(getattr(config, "MODEL", None), getattr(config, "REASONING_MODEL_PREFIX", None))
        except Exception:
            reasoning_model = False

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
        if reasoning_model:
            params[REQUEST_PARAM_TEMPERATURE] = 1
        elif getattr(config, "TEMPERATURE", None) is not None:
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

        # Call OpenAI Responses API (initial call) with cancellable helper
        response = _cancellable_responses_create(client.responses.create, params)

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
        used_estimate = False
        try:
            usage = getattr(response, "usage", None)
            if usage is None:
                actual_tokens = None
                used_estimate = True
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
                if actual_tokens is None:
                    used_estimate = True
                else:
                    used_estimate = False
            try:
                rid = getattr(response, ID_KEY, None)
            except Exception:
                rid = None
            try:
                mname = strip_openai_prefix(getattr(config, "MODEL", None)) if getattr(config, "MODEL", None) is not None else None
            except Exception:
                mname = None
            try:
                if isinstance(usage, dict):
                    total = usage.get("total_tokens") or usage.get("total_token_count") or usage.get("total")
                    prompt = usage.get("prompt_tokens")
                    completion = usage.get("completion_tokens")
                    input_tokens = usage.get("input_tokens")
                    output_tokens = usage.get("output_tokens")
                    reasoning_tokens = usage.get("reasoning_tokens")
                else:
                    total = getattr(usage, "total_tokens", None) or getattr(usage, "total_token_count", None) or getattr(usage, "total", None)
                    prompt = getattr(usage, "prompt_tokens", None)
                    completion = getattr(usage, "completion_tokens", None)
                    input_tokens = getattr(usage, "input_tokens", None)
                    output_tokens = getattr(usage, "output_tokens", None)
                    reasoning_tokens = getattr(usage, "reasoning_tokens", None)
            except Exception:
                total = prompt = completion = input_tokens = output_tokens = reasoning_tokens = None
            try:
                effective_prompt_tokens = prompt if prompt is not None else input_tokens
                effective_completion_tokens = completion if completion is not None else output_tokens
                effective_reasoning_tokens = reasoning_tokens
                if effective_reasoning_tokens is None:
                    details = None
                    try:
                        if isinstance(usage, dict):
                            details = usage.get("output_tokens_details")
                        else:
                            details = getattr(usage, "output_tokens_details", None)
                    except Exception:
                        details = None
                    try:
                        if isinstance(details, dict):
                            effective_reasoning_tokens = details.get("reasoning_tokens")
                        else:
                            effective_reasoning_tokens = getattr(details, "reasoning_tokens", None)
                    except Exception:
                        effective_reasoning_tokens = None
                logger.info(
                    "Responses usage model=%s id=%s total=%s prompt=%s completion=%s input=%s output=%s reasoning=%s raw=%r",
                    mname,
                    rid,
                    total,
                    effective_prompt_tokens,
                    effective_completion_tokens,
                    input_tokens,
                    output_tokens,
                    effective_reasoning_tokens,
                    usage,
                )
            except Exception:
                pass
        except Exception:
            actual_tokens = None
            used_estimate = True

        # If actual_tokens is None, set to 0 to avoid None propagation
        if actual_tokens is None:
            actual_tokens = 0

        # Update token usage and rate limiter immediately for the initial response
        try:
            update_token_usage(actual_tokens, used_estimate=used_estimate, response=response)
            logger.debug(
                f"Updated token usage with {actual_tokens} tokens from OpenAI response"
            )
        except Exception:
            logger.exception("Failed to update token usage after OpenAI response")

        try:
            if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
                rate_limiter.RATE_LIMITER.add_request(actual_tokens, request_id=request_id)
                logger.debug(
                    f"Added request of {actual_tokens} tokens to rate limiter (request_id={request_id})"
                )
        except Exception:
            logger.exception("Failed to add request to rate limiter after OpenAI response")

        # Begin function/tool call handling loop (up to max iterations)
        last_response = response
        max_iterations = MAX_FUNCTION_CALL_ITERATIONS
        iteration = 0
        last_iteration_had_calls = False

        # Collect function call outputs across iterations for potential summarization and to send aggregated follow-ups.
        # We collect both the serialized follow-up items (all_function_call_outputs) that will be sent back to the Responses API
        # and a summarization-friendly representation (all_summarization_outputs) built via build_function_call_output_item.
        all_function_call_outputs = []

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
                    output_payload = serialize_tool_output(result_or_error)
                except Exception:
                    try:
                        output_payload = serialize_tool_output(
                            {"error": "Unable to serialize tool result"}
                        )
                    except Exception:
                        output_payload = SERIALIZATION_FAILED_STR

                # Truncate serialized output to configured per-tool token limit to avoid oversized follow-ups.
                try:
                    token_limit = int(config.TOOL_OUTPUT_TOKEN_LIMIT)
                    truncated_output = truncate_to_token_limit(
                        output_payload, token_limit, model=strip_openai_prefix(config.MODEL)
                    )
                except Exception:
                    # If truncation fails for any reason, fall back to the original serialized payload.
                    logger.exception("Failed to truncate tool output; using full serialized output")
                    truncated_output = output_payload

                item = {
                    TYPE_KEY: FUNCTION_CALL_OUTPUT_TYPE,
                    "call_id": call_id,
                    "output": truncated_output,
                }

                function_call_outputs.append(item)

                # Also collect across iterations:
                # - append the serialized follow-up item that will be sent back to the Responses API
                # - append a summarization-friendly representation via build_function_call_output_item
                try:
                    try:
                        summary_item = build_function_call_output_item(call_id, result_or_error, serialized_output=truncated_output)
                        try:
                            summary_item['parent_response_id'] = getattr(last_response, ID_KEY, None)
                        except Exception:
                            # If setting parent_response_id fails, proceed without it
                            pass
                        all_function_call_outputs.append(summary_item)
                    except Exception:
                        # If build_function_call_output_item itself fails, attempt to append a minimal structure
                        minimal = {"id": call_id, "result": result_or_error}
                        try:
                            minimal['parent_response_id'] = getattr(last_response, ID_KEY, None)
                        except Exception:
                            pass
                        all_function_call_outputs.append(minimal)
                except Exception:
                    logger.exception("Failed to append to all_function_call_outputs")

                # Summarization item omitted.

            # If we have outputs from executing tools, send them back as a follow-up response
            if function_call_outputs:
                try:
                    followup_params = {REQUEST_PARAM_MODEL: strip_openai_prefix(config.MODEL)}
                    # Ensure previous_response_id is the last persisted response id
                    if hasattr(config, "RESPONSE_ID") and getattr(config, "RESPONSE_ID"):
                        followup_params[REQUEST_PREV_RESPONSE_ID] = getattr(config, "RESPONSE_ID")
                    followup_params[REQUEST_PARAM_INPUT] = function_call_outputs

                    # Preserve optional params
                    if reasoning_model:
                        followup_params[REQUEST_PARAM_TEMPERATURE] = 1
                    elif getattr(config, "TEMPERATURE", None) is not None:
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

                    iw = getattr(config, "MODEL_INPUT_WINDOW", None)
                    cw = getattr(config, "MODEL_CONTEXT_WINDOW", None)
                    input_window = iw if isinstance(iw, int) and iw > 0 else (cw if isinstance(cw, int) and cw > 0 else None)
                    # Effective budget = safety-margined input_window. Used
                    # for "should I trim" and "is this still too big" checks.
                    # The TRIM TARGET below stays at 80% of input_window
                    # (tighter than the safety budget) so trimming reliably
                    # brings the payload below the effective budget.
                    effective_input_window = (
                        int(input_window * INPUT_WINDOW_SAFETY_RATIO)
                        if input_window is not None else None
                    )
                    if input_window is not None:
                        try:
                            followup_input = followup_params.get(REQUEST_PARAM_INPUT)
                            if isinstance(followup_input, list):
                                followup_tokens = count_message_tokens(followup_input)
                                logger.info(
                                    "Pre-flight follow-up payload token check: original=%s tokens, effective limit=%s tokens (input_window=%s, safety=%.2f)",
                                    followup_tokens,
                                    effective_input_window,
                                    input_window,
                                    INPUT_WINDOW_SAFETY_RATIO,
                                )
                                if followup_tokens > effective_input_window:
                                    trim_target = max(1, int(input_window * 0.8))
                                    trimmed_input = []
                                    running_tokens = 0
                                    note_prefix = "[Trimmed to fit context window] "
                                    note_tokens = count_message_tokens(note_prefix)
                                    for idx, fc_item in enumerate(followup_input):
                                        if not isinstance(fc_item, dict) or fc_item.get(TYPE_KEY) != FUNCTION_CALL_OUTPUT_TYPE:
                                            continue
                                        try:
                                            call_id = fc_item.get("call_id")
                                            output_text = fc_item.get("output")
                                            if output_text is None:
                                                output_text = ""
                                            if not isinstance(output_text, str):
                                                try:
                                                    output_text = json.dumps(output_text)
                                                except Exception:
                                                    output_text = str(output_text)
                                            if idx == 0:
                                                output_text = note_prefix + output_text
                                            candidate_item = {
                                                TYPE_KEY: FUNCTION_CALL_OUTPUT_TYPE,
                                                "call_id": call_id,
                                                "output": output_text,
                                            }
                                            candidate_tokens = count_message_tokens(candidate_item)
                                            if running_tokens + candidate_tokens > trim_target and trimmed_input:
                                                break
                                            trimmed_input.append(candidate_item)
                                            running_tokens += candidate_tokens
                                        except Exception:
                                            logger.exception("Failed while trimming a follow-up function_call_output item")
                                            continue
                                    if trimmed_input:
                                        logger.warning(
                                            "Trimmed follow-up payload from %s tokens to approximately %s tokens (target %s tokens; note overhead %s tokens); retained %s tool outputs",
                                            followup_tokens,
                                            running_tokens + note_tokens,
                                            trim_target,
                                            note_tokens,
                                            len(trimmed_input),
                                        )
                                        followup_params[REQUEST_PARAM_INPUT] = trimmed_input
                                    else:
                                        logger.warning(
                                            "Follow-up payload exceeded context window (%s tokens > %s) but trimming produced no viable payload; continuing with original payload",
                                            followup_tokens,
                                            input_window,
                                        )
                            else:
                                logger.debug(
                                    "Skipping follow-up payload trimming because REQUEST_PARAM_INPUT is not a list"
                                )
                        except Exception:
                            logger.exception("Failed during pre-flight token budget check for follow-up payload")
                        followup_params = token_budgeter(
                            followup_params, 
                            input_window=input_window,
                            model_name=getattr(config, "MODEL", None)
                        )
                        try:
                            followup_input = followup_params.get(REQUEST_PARAM_INPUT)
                            if isinstance(followup_input, list):
                                final_followup_tokens = count_message_tokens(followup_input)
                                logger.info(
                                    "Pre-flight follow-up payload token check after budgeting: final=%s tokens, limit=%s tokens",
                                    final_followup_tokens,
                                    input_window,
                                )
                                if final_followup_tokens > effective_input_window:
                                    logger.warning(
                                        "Skipping follow-up responses.create because final payload still exceeds effective context window (%s tokens > %s; safety-margined from %s)",
                                        final_followup_tokens,
                                        effective_input_window,
                                        input_window,
                                    )
                                    break
                            else:
                                logger.debug(
                                    "Skipping final follow-up payload token check because REQUEST_PARAM_INPUT is not a list"
                                )
                        except Exception:
                            logger.exception("Failed during final pre-flight token budget check for follow-up payload")
                    else:
                        logger.debug(f"Skipping token budgeting: invalid MODEL_INPUT_WINDOW={iw!r}")

                    # H2: Preflight rate-limit gate for tool-call follow-up.
                    # Previously, follow-up responses.create calls only recorded
                    # tokens post-hoc, allowing a tool loop to burst past the
                    # configured TPM before any cooldown fired.
                    try:
                        if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
                            try:
                                followup_input = followup_params.get(REQUEST_PARAM_INPUT)
                                if isinstance(followup_input, list):
                                    preflight_tokens = count_message_tokens(followup_input)
                                else:
                                    preflight_tokens = count_message_tokens(
                                        [{"role": "user", "content": str(followup_input or "")}]
                                    )
                            except Exception:
                                logger.exception(
                                    "Failed to estimate follow-up payload tokens for rate-limit preflight; using 0"
                                )
                                preflight_tokens = 0
                            wait_result = rate_limiter.RATE_LIMITER.wait_if_needed(preflight_tokens)
                            if wait_result is None:
                                logger.warning(
                                    "Skipping follow-up responses.create: estimated tokens (%s) exceed rate-limiter safety threshold",
                                    preflight_tokens,
                                )
                                break
                    except Exception:
                        logger.exception(
                            "Rate-limit preflight check failed for follow-up responses.create; proceeding without gating"
                        )

                    # Follow-up call with cancellable helper
                    followup_response = _cancellable_responses_create(client.responses.create, followup_params)

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
                    follow_used_estimate = False
                    try:
                        usage = getattr(followup_response, "usage", None)
                        if usage is None:
                            follow_tokens = None
                            follow_used_estimate = True
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
                            if follow_tokens is None:
                                follow_used_estimate = True
                            else:
                                follow_used_estimate = False
                    except Exception:
                        follow_tokens = None
                        follow_used_estimate = True

                    if follow_tokens is None:
                        follow_tokens = 0

                    # Update token usage and rate limiter for follow-up
                    try:
                        update_token_usage(follow_tokens, used_estimate=follow_used_estimate, response=followup_response)
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
                        # Build a summary instruction that explicitly prevents further tool usage.
                        # NOTE: We intentionally do NOT include tools in the summarization follow-up
                        # parameters to prevent the model from issuing additional tool/function calls.
                        summary_instruction = (
                            "Please summarize the previous response and the results of the function/tool calls into a concise summary. "
                            "Do NOT call any tools or request further function executions. Only provide a brief summary of the outputs."
                        )

                        # Compute summary token allotment; preserve previous behavior
                        try:
                            model_window = int(getattr(config, "MODEL_OUTPUT_WINDOW"))
                            computed_summary_tokens = max(
                                int(SUMMARY_MAX_OUTPUT_TOKENS // 2),
                                min(int(model_window * 0.08), int(SUMMARY_MAX_OUTPUT_TOKENS))
                            )
                        except Exception:
                            computed_summary_tokens = int(SUMMARY_MAX_OUTPUT_TOKENS)

                        logger.debug(
                            f"[SUMMARIZATION] Using SUMMARY_MAX_OUTPUT_TOKENS={computed_summary_tokens} "
                            f"(MODEL_OUTPUT_WINDOW={getattr(config, 'MODEL_OUTPUT_WINDOW', 'n/a')})"
                        )

                        # Build summarization follow-up input: include all aggregated function_call outputs
                        # collected across iterations, followed by the explicit summary instruction that tells
                        # the model NOT to call any tools. Intentionally omit REQUEST_PARAM_TOOLS here.
                        try:
                            # Compute parent_response_id by scanning aggregated function outputs for the first non-empty parent_response_id
                            parent_resp_id = None
                            try:
                                for fo in all_function_call_outputs:
                                    try:
                                        if isinstance(fo, dict):
                                            pr = fo.get("parent_response_id")
                                            if pr:
                                                parent_resp_id = pr
                                                break
                                    except Exception:
                                        continue
                            except Exception:
                                parent_resp_id = None
                            if parent_resp_id is None:
                                parent_resp_id = getattr(config, "RESPONSE_ID")

                            # Use build_summarization_followup_params to obtain sanitized parameters and mapping
                            sfp = build_summarization_followup_params(
                                prev_response_id=parent_resp_id,
                                function_call_outputs=all_function_call_outputs,
                                summary_instruction=summary_instruction,
                                model=strip_openai_prefix(config.MODEL),
                                max_output_tokens=computed_summary_tokens,
                            )

                            # Map sanitized helper output into API parameter names, ensure instruction appended after outputs
                            summary_params = {}

                            # model -> REQUEST_PARAM_MODEL: use returned sfp['model'] if present, else fallback
                            try:
                                if isinstance(sfp, dict) and sfp.get("model"):
                                    summary_params[REQUEST_PARAM_MODEL] = strip_openai_prefix(sfp.get("model"))
                                else:
                                    summary_params[REQUEST_PARAM_MODEL] = strip_openai_prefix(config.MODEL)
                            except Exception:
                                summary_params[REQUEST_PARAM_MODEL] = strip_openai_prefix(config.MODEL)

                            # previous_response_id -> REQUEST_PREV_RESPONSE_ID: use returned sfp field if present, else fallback
                            try:
                                if isinstance(sfp, dict) and (sfp.get("prev_response_id") or sfp.get("parent_response_id")):
                                    summary_params[REQUEST_PREV_RESPONSE_ID] = sfp.get("prev_response_id") or sfp.get("parent_response_id")
                                else:
                                    summary_params[REQUEST_PREV_RESPONSE_ID] = getattr(config, "RESPONSE_ID")
                            except Exception:
                                summary_params[REQUEST_PREV_RESPONSE_ID] = getattr(config, "RESPONSE_ID")

                            # function_call_outputs -> REQUEST_PARAM_INPUT (as list), then append explicit typed instruction
                            try:
                                func_outputs = list(sfp.get("function_call_outputs") or []) if isinstance(sfp, dict) else list(all_function_call_outputs)
                            except Exception:
                                func_outputs = list(all_function_call_outputs)

                            # Convert aggregated function outputs into role/content assistant messages for summarization follow-up
                            try:
                                summary_input_messages = []
                                # We'll also build typed function_call_output items to include in the API payload
                                typed_function_call_items = []
                                for fo in func_outputs:
                                    try:
                                        # If item is a dict, extract call id and output field robustly
                                        if isinstance(fo, dict):
                                            call_id = None
                                            # Prefer 'id' then 'call_id'
                                            try:
                                                call_id = fo.get("id") or fo.get("call_id")
                                            except Exception:
                                                call_id = None

                                            # Attempt to find output string in common locations
                                            out_val = None
                                            try:
                                                # Preferentially use output, then serialized_output, result, text, content, else entire item
                                                try:
                                                    out_val = fo.get("output") or fo.get("serialized_output") or fo.get("result") or fo.get("text") or fo.get("content") or fo
                                                except Exception:
                                                    out_val = fo
                                            except Exception:
                                                out_val = fo

                                            # Check parent_response_id filtering: only include items whose parent_response_id == parent_resp_id (if parent_response_id is present)
                                            try:
                                                fo_parent = fo.get("parent_response_id") if isinstance(fo, dict) else None
                                            except Exception:
                                                fo_parent = None
                                            try:
                                                if fo_parent is not None and parent_resp_id is not None and fo_parent != parent_resp_id:
                                                    logger.debug(f"Skipping function output with call_id={call_id} due to parent_response_id mismatch: {fo_parent} != {parent_resp_id}")
                                                    continue
                                            except Exception:
                                                # If checking fails, proceed to include item
                                                pass

                                            # Coerce out_val to string safely for assistant-facing message
                                            if isinstance(out_val, (dict, list)):
                                                try:
                                                    out_str = json.dumps(out_val)
                                                except Exception:
                                                    out_str = str(out_val)
                                            else:
                                                try:
                                                    out_str = str(out_val)
                                                except Exception:
                                                    out_str = ""

                                            # Build typed function_call_output item to include in the API input
                                            try:
                                                typed_item = { TYPE_KEY: FUNCTION_CALL_OUTPUT_TYPE, "call_id": call_id, "output": out_str }
                                                typed_function_call_items.append(typed_item)
                                            except Exception:
                                                # fallback to minimal typed item
                                                try:
                                                    typed_function_call_items.append({ TYPE_KEY: FUNCTION_CALL_OUTPUT_TYPE, "call_id": call_id, "output": out_str })
                                                except Exception:
                                                    pass

                                            if call_id:
                                                content = f"Function call {call_id}: {out_str}"
                                            else:
                                                content = out_str

                                            summary_input_messages.append({ "role": "assistant", "content": content })
                                        else:
                                            # Non-dict items: coerce to string
                                            s = str(fo)
                                            # Also include typed item for non-dict as best-effort
                                            try:
                                                typed_function_call_items.append({ TYPE_KEY: FUNCTION_CALL_OUTPUT_TYPE, "call_id": None, "output": s })
                                            except Exception:
                                                pass
                                            summary_input_messages.append({ "role": "assistant", "content": s })
                                    except Exception:
                                        logger.exception("Failed converting a function output item to assistant message for summarization")
                                        raise

                                # Append the explicit user instruction as the last message
                                try:
                                    summary_input_messages.append({"role": USER_ROLE, "content": summary_instruction})
                                except Exception:
                                    summary_input_messages.append({"role": USER_ROLE, "content": summary_instruction})

                                # Combine typed items and assistant messages into final API input payload: typed items first, then assistant messages/instruction.
                                try:
                                    combined_input = []
                                    # Add typed items first
                                    combined_input.extend(typed_function_call_items)
                                    # Then append assistant messages
                                    combined_input.extend(summary_input_messages)
                                    summary_params[REQUEST_PARAM_INPUT] = combined_input
                                except Exception:
                                    # If combining fails, fall back to assistant messages only
                                    summary_params[REQUEST_PARAM_INPUT] = summary_input_messages

                                # Estimate tokens for the assembled input for logging: convert typed items to assistant messages for estimation
                                try:
                                    estimation_messages = []
                                    # Convert typed items into assistant messages for estimation
                                    for t in typed_function_call_items:
                                        try:
                                            cid = t.get("call_id")
                                            out = t.get("output")
                                            out_str = ""
                                            if isinstance(out, (dict, list)):
                                                try:
                                                    out_str = json.dumps(out)
                                                except Exception:
                                                    out_str = str(out)
                                            else:
                                                out_str = str(out) if out is not None else ""
                                            if cid:
                                                estimation_messages.append({"role": "assistant", "content": f"Function call {cid}: {out_str}"})
                                            else:
                                                estimation_messages.append({"role": "assistant", "content": out_str})
                                        except Exception:
                                            continue
                                    # Append assistant messages (including the final user instruction) to estimation messages
                                    try:
                                        for m in summary_input_messages:
                                            if isinstance(m, dict) and m.get("role") and m.get("content") is not None:
                                                estimation_messages.append(m)
                                            else:
                                                estimation_messages.append({"role": "assistant", "content": str(m)})
                                    except Exception:
                                        pass
                                    try:
                                        estimated_summary_tokens = estimate_response_tokens(estimation_messages)
                                        logger.debug(f"Estimated tokens for summarization follow-up input: {estimated_summary_tokens}")
                                    except Exception:
                                        logger.debug("Failed to estimate tokens for summarization follow-up input")
                                except Exception:
                                    logger.debug("Failed to build estimation messages for summarization follow-up")
                            except Exception:
                                # If conversion fails, log and fall back to sending only the summary instruction
                                logger.exception("Failed to build summary_input_messages from function outputs; falling back to instruction-only summarization")
                                summary_params[REQUEST_PARAM_INPUT] = [{"role": USER_ROLE, "content": summary_instruction}]
                            # max_output_tokens -> REQUEST_PARAM_MAX_OUTPUT_TOKENS
                            try:
                                if isinstance(sfp, dict) and sfp.get("max_output_tokens") is not None:
                                    summary_params[REQUEST_PARAM_MAX_OUTPUT_TOKENS] = sfp.get("max_output_tokens")
                                else:
                                    summary_params[REQUEST_PARAM_MAX_OUTPUT_TOKENS] = computed_summary_tokens
                            except Exception:
                                summary_params[REQUEST_PARAM_MAX_OUTPUT_TOKENS] = computed_summary_tokens

                        except Exception:
                            # Fallback: if building summary_inputs fails, revert to simple instruction-only summarization
                            try:
                                summary_inputs = list(all_function_call_outputs)
                                # Convert fallback summary_inputs into assistant messages
                                try:
                                    summary_input_messages = []
                                    typed_function_call_items = []
                                    for fo in summary_inputs:
                                        try:
                                            if isinstance(fo, dict):
                                                call_id = fo.get("id") or fo.get("call_id")
                                                out_val = fo.get("output") if fo.get("output") is not None else fo
                                                if isinstance(out_val, (dict, list)):
                                                    try:
                                                        out_str = json.dumps(out_val)
                                                    except Exception:
                                                        out_str = str(out_val)
                                                else:
                                                    out_str = str(out_val)
                                                # Build typed item
                                                try:
                                                    typed_function_call_items.append({ TYPE_KEY: FUNCTION_CALL_OUTPUT_TYPE, "call_id": call_id, "output": out_str })
                                                except Exception:
                                                    pass
                                                if call_id:
                                                    content = f"Function call {call_id}: {out_str}"
                                                else:
                                                    content = out_str
                                                summary_input_messages.append({"role": "assistant", "content": content})
                                            else:
                                                s = str(fo)
                                                try:
                                                    typed_function_call_items.append({ TYPE_KEY: FUNCTION_CALL_OUTPUT_TYPE, "call_id": None, "output": s })
                                                except Exception:
                                                    pass
                                                summary_input_messages.append({"role": "assistant", "content": s})
                                        except Exception:
                                            logger.exception("Failed converting a fallback function output item to assistant message for summarization")
                                            raise
                                    # Append the summary instruction
                                    summary_input_messages.append({"role": USER_ROLE, "content": summary_instruction})
                                    # Combine typed items and assistant messages
                                    try:
                                        combined_input = []
                                        combined_input.extend(typed_function_call_items)
                                        combined_input.extend(summary_input_messages)
                                        summary_params = {
                                            REQUEST_PARAM_MODEL: strip_openai_prefix(config.MODEL),
                                            REQUEST_PREV_RESPONSE_ID: getattr(config, "RESPONSE_ID"),
                                            REQUEST_PARAM_INPUT: combined_input,
                                            REQUEST_PARAM_MAX_OUTPUT_TOKENS: computed_summary_tokens,
                                        }
                                    except Exception:
                                        summary_params = {
                                            REQUEST_PARAM_MODEL: strip_openai_prefix(config.MODEL),
                                            REQUEST_PREV_RESPONSE_ID: getattr(config, "RESPONSE_ID"),
                                            REQUEST_PARAM_INPUT: summary_input_messages,
                                            REQUEST_PARAM_MAX_OUTPUT_TOKENS: computed_summary_tokens,
                                        }
                                    # Estimate tokens for fallback assembled input
                                    try:
                                        estimation_messages = []
                                        for t in typed_function_call_items:
                                            try:
                                                cid = t.get("call_id")
                                                out = t.get("output")
                                                out_str = ""
                                                if isinstance(out, (dict, list)):
                                                    try:
                                                        out_str = json.dumps(out)
                                                    except Exception:
                                                        out_str = str(out)
                                                else:
                                                    out_str = str(out) if out is not None else ""
                                                if cid:
                                                    estimation_messages.append({"role": "assistant", "content": f"Function call {cid}: {out_str}"})
                                                else:
                                                    estimation_messages.append({"role": "assistant", "content": out_str})
                                            except Exception:
                                                continue
                                        for m in summary_input_messages:
                                            if isinstance(m, dict) and m.get("content") is not None:
                                                estimation_messages.append(m)
                                            else:
                                                estimation_messages.append({"role": "assistant", "content": str(m)})
                                        try:
                                            estimated_summary_tokens = estimate_response_tokens(estimation_messages)
                                            logger.debug(f"Estimated tokens for summarization follow-up input (fallback): {estimated_summary_tokens}")
                                        except Exception:
                                            logger.debug("Failed to estimate tokens for summarization follow-up input (fallback)")
                                    except Exception:
                                        logger.debug("Failed to build estimation messages for summarization follow-up (fallback)")
                                except Exception:
                                    logger.exception("Failed to build summary_input_messages in fallback; using instruction-only payload")
                                    summary_params = {
                                        REQUEST_PARAM_MODEL: strip_openai_prefix(config.MODEL),
                                        REQUEST_PREV_RESPONSE_ID: getattr(config, "RESPONSE_ID"),
                                        REQUEST_PARAM_INPUT: {"role": USER_ROLE, "content": summary_instruction},
                                        REQUEST_PARAM_MAX_OUTPUT_TOKENS: computed_summary_tokens,
                                    }
                            except Exception:
                                summary_params = {
                                    REQUEST_PARAM_MODEL: strip_openai_prefix(config.MODEL),
                                    REQUEST_PREV_RESPONSE_ID: getattr(config, "RESPONSE_ID"),
                                    REQUEST_PARAM_INPUT: {"role": USER_ROLE, "content": summary_instruction},
                                    REQUEST_PARAM_MAX_OUTPUT_TOKENS: computed_summary_tokens,
                                }

                        # Before sending summarization follow-up, log a visible warning with the prev_response_id to be used and call IDs included.
                        try:
                            try:
                                # Determine prev_response_id to be used for logging
                                prev_id_for_logging = None
                                if isinstance(sfp, dict) and (sfp.get("prev_response_id") or sfp.get("parent_response_id")):
                                    prev_id_for_logging = sfp.get("prev_response_id") or sfp.get("parent_response_id")
                                else:
                                    prev_id_for_logging = parent_resp_id if 'parent_resp_id' in locals() else getattr(config, "RESPONSE_ID")
                            except Exception:
                                prev_id_for_logging = getattr(config, "RESPONSE_ID")

                            # Collect call_ids from typed_function_call_items if present, else from func_outputs
                            call_ids = []
                            try:
                                if 'typed_function_call_items' in locals() and isinstance(typed_function_call_items, list) and typed_function_call_items:
                                    for t in typed_function_call_items:
                                        try:
                                            if isinstance(t, dict):
                                                cid = t.get("call_id")
                                                call_ids.append(cid)
                                        except Exception:
                                            continue
                                else:
                                    # fallback: extract from func_outputs
                                    if isinstance(func_outputs, list):
                                        for fo in func_outputs:
                                            try:
                                                if isinstance(fo, dict):
                                                    cid = fo.get("call_id") or fo.get("id")
                                                    call_ids.append(cid)
                                            except Exception:
                                                continue
                            except Exception:
                                call_ids = []

                            logger.info("Summarization follow-up will use previous_response_id=%s and include call_ids=%s", prev_id_for_logging, call_ids)
                        except Exception:
                            logger.exception("Failed to log summarization follow-up warning")

                        logger.debug("Sending summarization follow-up due to function call iteration truncation")
                        # Pre-send estimation/logging step for summarization payload
                        try:
                            try:
                                est_input = summary_params.get(REQUEST_PARAM_INPUT)
                            except Exception:
                                est_input = summary_params.get(REQUEST_PARAM_INPUT) if isinstance(summary_params, dict) else None
                            estimation_messages = []
                            if isinstance(est_input, list):
                                for itm in est_input:
                                    try:
                                        if isinstance(itm, dict):
                                            # Typed function_call_output item
                                            if itm.get(TYPE_KEY) == FUNCTION_CALL_OUTPUT_TYPE:
                                                cid = itm.get("call_id")
                                                out_val = itm.get("output") or itm.get("serialized_output") or itm.get("result") or itm.get("text") or itm.get("content") or itm
                                                if isinstance(out_val, (dict, list)):
                                                    try:
                                                        out_str = json.dumps(out_val)
                                                    except Exception:
                                                        out_str = str(out_val)
                                                else:
                                                    out_str = str(out_val) if out_val is not None else ""
                                                if cid:
                                                    estimation_messages.append({"role": "assistant", "content": f"Function call {cid}: {out_str}"})
                                                else:
                                                    estimation_messages.append({"role": "assistant", "content": out_str})
                                            # Already structured message with role/content
                                            elif itm.get("role") and itm.get("content") is not None:
                                                estimation_messages.append({"role": itm.get("role"), "content": itm.get("content")})
                                            else:
                                                # Fallback: stringify
                                                try:
                                                    s = json.dumps(itm) if not isinstance(itm, str) else itm
                                                except Exception:
                                                    s = str(itm)
                                                estimation_messages.append({"role": "assistant", "content": s})
                                        else:
                                            # Non-dict -> coerce to assistant message
                                            estimation_messages.append({"role": "assistant", "content": str(itm)})
                                    except Exception:
                                        continue
                            elif isinstance(est_input, dict):
                                if est_input.get("role") and est_input.get("content") is not None:
                                    estimation_messages.append({"role": est_input.get("role"), "content": est_input.get("content")})
                                else:
                                    try:
                                        s = json.dumps(est_input) if not isinstance(est_input, str) else est_input
                                    except Exception:
                                        s = str(est_input)
                                    estimation_messages.append({"role": "assistant", "content": s})
                            else:
                                # Single string or other single item
                                estimation_messages.append({"role": "assistant", "content": str(est_input)})
                            try:
                                estimated_tokens = estimate_response_tokens(estimation_messages)
                                logger.debug(f"Estimated tokens for summarization payload before sending: {estimated_tokens}")
                            except Exception:
                                logger.debug("Failed to estimate tokens for summarization payload before sending")
                        except Exception:
                            logger.exception("Failed building estimation messages for summarization payload")

                        # H3: Preflight rate-limit gate for summarization follow-up.
                        # Previously this call only recorded tokens post-hoc,
                        # allowing the summarization burst to bypass the
                        # configured TPM cap.
                        summary_preflight_ok = True
                        try:
                            if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
                                try:
                                    summary_preflight_tokens = int(estimated_tokens) if estimated_tokens is not None else 0
                                except Exception:
                                    summary_preflight_tokens = 0
                                if summary_preflight_tokens <= 0:
                                    try:
                                        summary_input = summary_params.get(REQUEST_PARAM_INPUT)
                                        if isinstance(summary_input, list):
                                            summary_preflight_tokens = count_message_tokens(summary_input)
                                        elif summary_input is not None:
                                            summary_preflight_tokens = count_message_tokens(
                                                [{"role": "user", "content": str(summary_input)}]
                                            )
                                    except Exception:
                                        logger.exception(
                                            "Failed to estimate summarization payload tokens for rate-limit preflight; using 0"
                                        )
                                        summary_preflight_tokens = 0
                                wait_result = rate_limiter.RATE_LIMITER.wait_if_needed(summary_preflight_tokens)
                                if wait_result is None:
                                    logger.warning(
                                        "Skipping summarization follow-up: estimated tokens (%s) exceed rate-limiter safety threshold",
                                        summary_preflight_tokens,
                                    )
                                    summary_preflight_ok = False
                        except Exception:
                            logger.exception(
                                "Rate-limit preflight check failed for summarization follow-up; proceeding without gating"
                            )

                        if not summary_preflight_ok:
                            summary_response = None
                        else:
                            # Summarization call with cancellable helper and label
                            summary_response = _cancellable_responses_create(client.responses.create, summary_params, progress_label="Summarizing ")

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
                        summary_used_estimate = False
                        try:
                            usage = getattr(summary_response, "usage", None)
                            if usage is None:
                                summary_tokens = None
                                summary_used_estimate = True
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
                                if summary_tokens is None:
                                    summary_used_estimate = True
                                else:
                                    summary_used_estimate = False
                        except Exception:
                            summary_tokens = None
                            summary_used_estimate = True

                        if summary_tokens is None:
                            summary_tokens = 0

                        # Update token usage and rate limiter for summary
                        try:
                            update_token_usage(summary_tokens, used_estimate=summary_used_estimate, response=summary_response)
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

def response_completion(user_input, tool_descriptions, gemini_tool_descriptions, log_prefix="", error_message="Error during responses API completion"):
    """Main entry point for responses API completion.

    This function handles the complete flow for responses API:
    1. Validates configuration
    2. Prepares messages
    3. Estimates tokens
    4. Validates messages
    5. Calls responses API (cancellable via Ctrl-C)
    6. Processes response
    7. Updates token usage

    Ctrl-C will cancel an in-flight API wait and return (None, "Cancelled by user").

    Args:
        user_input (str): The user's input/query
        tool_descriptions (list): Tool specifications for the current model
        gemini_tool_descriptions (list): Alternative tool specifications (for Gemini models)
        log_prefix (str): Prefix for log messages
        error_message (str): Default error message

    Returns:
        tuple: (response, error_message) where response is None on error or cancellation
    """
    try:
        logger.debug(f"{log_prefix} Starting responses API completion")

        # Validate configuration
        validate_responses_config()

        # Prepare messages for responses API
        messages = prepare_response_messages(user_input)

        # Estimate token count
        estimated_tokens = estimate_response_tokens(messages)

        # Compute estimated request including reasoning completion budget if applicable
        reasoning_allowance = (getattr(config, "REASONING_MAX_COMPLETION_TOKENS", 0) if is_reasoning_model(getattr(config, "MODEL", None), getattr(config, "REASONING_MODEL_PREFIX", None)) else 0)
        estimated_request = estimated_tokens + (reasoning_allowance or 0)

        # Validate message order
        try:
            validate_tool_message_order(messages)
        except ValueError as ve:
            logger.error(f"Message validation failed for responses API: {ve}")
            return None, str(ve)

        # Input window gating for responses API
        iw = getattr(config, "MODEL_INPUT_WINDOW", None)
        cw = getattr(config, "MODEL_CONTEXT_WINDOW", None)
        input_window_limit = iw if isinstance(iw, int) and iw > 0 else (cw if isinstance(cw, int) and cw > 0 else None)
        if input_window_limit is None:
            logger.debug("Input size gating is disabled: no valid MODEL_INPUT_WINDOW or MODEL_CONTEXT_WINDOW configured (responses API)")
        else:
            # Apply safety margin — count_message_tokens undercounts by 10-30%
            # vs. OpenAI's actual input-token tally for Responses API payloads
            # (server-side cached context, tool definitions, output-item wrapping).
            effective_input_window_limit = int(input_window_limit * INPUT_WINDOW_SAFETY_RATIO)
            if estimated_tokens > effective_input_window_limit:
                error_msg = (
                    f"Input too large: {estimated_tokens} tokens vs effective input window "
                    f"{effective_input_window_limit} (safety-margined from {input_window_limit}). "
                    f"Cannot send request to responses API. Please reduce your input or send a smaller request."
                )
                logger.error(error_msg)
                return None, error_msg

        # Apply rate limiting if configured
        if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
            wait_result = rate_limiter.RATE_LIMITER.wait_if_needed(estimated_request)
            if wait_result is None:
                error_msg = (
                    f"Rate limit safety threshold exceeded: {estimated_request} tokens. "
                    f"Model TPM limit {config.MODEL_MAX_TPM}. Reduce your input or wait before retrying."
                )
                logger.error(error_msg)
                return None, error_msg

        # M-rl2: per-request UUID shared between the cancellation and the
        # success-path accounting. If both fire (cancel records the estimate,
        # then the eventual provider response is processed and records the
        # actual count), add_request replaces the entry in place instead of
        # double-counting.
        request_id = uuid.uuid4().hex

        # Call responses API
        try:
            api_response = call_responses_api(messages, tool_descriptions, gemini_tool_descriptions, request_id=request_id)
        except KeyboardInterrupt:
            logger.info("Responses API call cancelled by user via Ctrl-C")
            # Conservative token accounting on cancellation
            try:
                update_token_usage(estimated_request, used_estimate=True)
                logger.debug(f"Conservatively updated token usage with {estimated_request} tokens on cancellation")
            except Exception:
                logger.exception("Failed to conservatively update token usage on cancellation")
            try:
                if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
                    rate_limiter.RATE_LIMITER.add_request(estimated_request, request_id=request_id)
                    logger.debug(f"Conservatively added cancellation request of {estimated_request} tokens to rate limiter (request_id={request_id})")
            except Exception:
                logger.exception("Failed to conservatively add cancellation request to rate limiter")
            return None, "Cancelled by user"

        # Convert response format
        response = convert_response_format(api_response)

        logger.debug(f"{log_prefix} Successfully completed responses API request")
        return response, None

    except Exception as e:
        return handle_response_errors(e, user_input)


def get_response_initial_completion(user_input, tool_descriptions, gemini_tool_descriptions):
    """Get initial response from responses API for the query.

    Args:
        user_input (str): The user's input/query
        tool_descriptions (list): Tool specifications for the current model
        gemini_tool_descriptions (list): Alternative tool specifications (for Gemini models)

    Returns:
        tuple: (response, error_message) where response is None on error
    """
    logger.debug("Getting initial responses API response...")
    return response_completion(
        user_input,
        tool_descriptions,
        gemini_tool_descriptions,
        log_prefix="Initial responses API request:",
        error_message="I apologize, but I encountered an error processing your request via responses API. Please try again",
    )
