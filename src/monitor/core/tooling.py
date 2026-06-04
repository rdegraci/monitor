import json
import logging

from monitor import config

logger = logging.getLogger(__name__)
from monitor.lib.tool_definitions import AVAILABLE_TOOLS
from monitor.lib.colors import red, blue, yellow, reset
from monitor.lib import rate_limiter

from monitor.lib.protocol_engine import configure_protocol_engine_message_history
from monitor.lib.token_management import (
    count_message_tokens,
    update_token_usage,
)  # All token counting/estimation now centralized here

LARGE_FILE_TOKEN_THRESHOLD = 1000
RECURSIVE_DIR_TOKEN_ESTIMATE = 500
SOURCE_MODIFICATION_TOKEN_ESTIMATE = 3000

# TC-2: cap on the depth of nested tool-call dispatches. handle_tool_call
# recurses when the model's reply also contains tool_calls; an adversarial
# prompt or runaway agent loop would otherwise stack-overflow. The active
# value lives in config.MAX_TOOL_CALL_DEPTH so it's tunable at runtime
# without an import-time freeze.

# TC-3: per-turn loop detector. Records (tool_name, canonical_args) for each
# tool call dispatched this turn. When the same signature has appeared the
# last config.MAX_REPEATED_TOOL_CALLS times in a row, handle_tool_call
# rejects the call without executing it — the model gets an error string
# routed back as the tool result so it can change strategy. Cleared when a
# new user turn enters handle_tool_call at _depth=0.
_RECENT_TOOL_CALLS: list[str] = []


def _tool_call_signature(name, args):
    """Stable hash of a tool call: 'name:<sorted-json-of-args>'.

    Sorted keys + default=str makes two calls with the same intent compare
    equal even if the model reorders kwargs or passes a non-string-keyed
    value. Falls back to repr() so a non-serializable arg never crashes
    the detector — at worst the signature becomes opaque, which is fine.
    """
    try:
        canonical = json.dumps(args, sort_keys=True, default=str) if args else "{}"
    except Exception:
        canonical = repr(args)
    return f"{name}:{canonical}"


def _check_repeated_call(name, args):
    """Append a signature; return True if the last N entries all match.

    N = config.MAX_REPEATED_TOOL_CALLS. Returns False (and still records)
    when the knob is 0 or negative — used as a kill switch.
    """
    max_reps = getattr(config, "MAX_REPEATED_TOOL_CALLS", 3)
    sig = _tool_call_signature(name, args)
    _RECENT_TOOL_CALLS.append(sig)
    if max_reps <= 0 or len(_RECENT_TOOL_CALLS) < max_reps:
        return False
    return all(s == sig for s in _RECENT_TOOL_CALLS[-max_reps:])


def parse_function_args(function_args):
    """Parse function arguments from string to dictionary"""
    try:
        if isinstance(function_args, str):
            return json.loads(function_args)
        return function_args
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing function arguments: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error parsing function arguments: {str(e)}", exc_info=True)
        raise


def execute_tool_call(tool_call):
    """Execute a single tool call and return the result

    All token counting and estimation is performed using centralized helpers in lib.token_management.

    TC-1: validate the tool_call structure before any key access. The previous
    direct ``tool_call["function"]["arguments"]`` / ``["name"]`` indexing was
    outside the try/except below, so a malformed dict raised an unhandled
    KeyError up to handle_tool_call — which had *already* appended the
    assistant message (with tool_calls) to history via extract_tool_calls.
    The result was an orphaned assistant tool_calls entry that the provider
    rejects with HTTP 400 on the next request.
    """
    logger.debug(f"Processing tool_call, type: {type(tool_call)}, value: {str(tool_call)[:300]}")

    # Structural validation — always return (None, error) on malformed input.
    if not isinstance(tool_call, dict):
        return None, f"Invalid tool call: expected dict, got {type(tool_call).__name__}"
    function_block = tool_call.get("function")
    if not isinstance(function_block, dict):
        return None, "Invalid tool call: missing or non-dict 'function' field"
    function_name = function_block.get("name")
    if not isinstance(function_name, str) or not function_name:
        return None, "Invalid tool call: missing or empty 'function.name'"
    function_args_raw = function_block.get("arguments", "")

    logger.debug(f"Executing function: {function_name}, arguments: {function_args_raw}")

    if function_name not in AVAILABLE_TOOLS:
        logger.error(f"Function {function_name} not found")
        return None, f"Key {function_name} not found in available_functions"

    try:
        # Parse function arguments
        function_args = parse_function_args(function_args_raw)

        # Apply rate limiting for high-token operations using centralized API
        if function_name in ["cat_file", "cat_file_range", "list_directory_contents", "create_file"]:
            if function_name in ("cat_file", "cat_file_range") and "path" in function_args:
                # Use count_message_tokens for accurate estimation
                try:
                    with open(function_args["path"], "r") as f:
                        content = f.read()
                        estimated_tokens = count_message_tokens({"role": "system", "content": content})
                        if estimated_tokens > LARGE_FILE_TOKEN_THRESHOLD:
                            if rate_limiter.RATE_LIMITER is not None:
                                rate_limiter.RATE_LIMITER.wait_if_needed(estimated_tokens)
                except (FileNotFoundError, PermissionError):
                    pass

            elif function_name == "list_directory_contents" and "path" in function_args:
                if function_args.get("recursive", False):
                    # Still use conservative estimate for recursion
                    if rate_limiter.RATE_LIMITER is not None:
                        rate_limiter.RATE_LIMITER.wait_if_needed(RECURSIVE_DIR_TOKEN_ESTIMATE)

        result = AVAILABLE_TOOLS[function_name](**function_args)
        logger.debug(f"Result: {result}")

        # Record usage for high-token operations using canonical counting API
        if (
            function_name in ["cat_file", "cat_file_range", "list_directory_contents"]
            and isinstance(result, str)
        ):
            estimated_tokens = count_message_tokens({"role": "system", "content": result})
            if estimated_tokens > LARGE_FILE_TOKEN_THRESHOLD:
                if rate_limiter.RATE_LIMITER is not None:
                    rate_limiter.RATE_LIMITER.add_request(estimated_tokens)

        return result, None
    except TypeError as e:
        error_msg = f"Error executing {function_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg
    except json.JSONDecodeError as e:
        error_msg = f"Error parsing arguments for {function_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg
    except Exception as e:
        error_msg = f"Unexpected error executing {function_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg


def handle_tool_call(response, _depth=0):
    """Orchestrate the handling of tool calls from LLM response.

    All token counting and estimation logic is routed through lib.token_management per project policy.

    TC-2: ``_depth`` tracks nested tool-call dispatches and bails at
    MAX_TOOL_CALL_DEPTH so a runaway tool-calls chain unwinds gracefully
    instead of stack-overflowing.
    """

    # Start of a new user turn — clear the per-turn loop-detector ledger so
    # the previous turn's signatures don't bleed forward.
    if _depth == 0:
        _RECENT_TOOL_CALLS.clear()

    max_depth = config.MAX_TOOL_CALL_DEPTH
    if _depth >= max_depth:
        logger.error(
            "handle_tool_call: depth %d reached MAX_TOOL_CALL_DEPTH %d; aborting chain",
            _depth, max_depth,
        )
        return (
            f"Tool-call chain exceeded the maximum depth of {max_depth}. "
            "Stopping to prevent runaway recursion. The user can retry with a fresh prompt."
        )

    # Fire a single half-way warning as a heads-up that this turn is running
    # a long autonomous chain. Equality (not >=) ensures we log exactly once
    # per chain instead of spamming every round past the threshold.
    if _depth == max_depth // 2:
        logger.warning(
            "handle_tool_call: depth %d of %d reached half of MAX_TOOL_CALL_DEPTH "
            "(long autonomous chain). The hard abort fires at %d.",
            _depth, max_depth, max_depth,
        )

    from monitor.core.conversation import (
        extract_tool_calls,
        append_to_history_with_count,
        get_llm_completion,
        process_response_by_finish_reason,
        update_conversation_history,
    )

    logger.debug("Handling tool call (depth=%d)...", _depth)

    # Extract tool calls
    tool_calls = extract_tool_calls(response)

    # Process each tool call
    for tool_call in tool_calls:
        logger.debug(f"Processing tool_call, type: {type(tool_call)}, value: {str(tool_call)[:300]}")

        # TC-1: extract tool_call_id defensively. extract_tool_calls has
        # already appended the assistant message (with tool_calls) to history,
        # so we MUST append a result message for each tool_call_id even when
        # the tool itself fails or the dict is malformed — otherwise the
        # next provider request 400s on orphaned tool_calls.
        if isinstance(tool_call, dict):
            tool_call_id = tool_call.get("id")
        else:
            tool_call_id = getattr(tool_call, "id", None)

        # TC-3: loop detector. Inspect the call BEFORE executing — if the same
        # (name, args) has fired MAX_REPEATED_TOOL_CALLS times in a row this
        # turn, the result obviously isn't going to change. Return an error
        # string to the model so it can change strategy or ask the user.
        loop_name = None
        loop_args = None
        if isinstance(tool_call, dict):
            fn_block = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else None
            if fn_block:
                loop_name = fn_block.get("name")
                try:
                    loop_args = parse_function_args(fn_block.get("arguments", ""))
                except Exception:
                    loop_args = fn_block.get("arguments")

        if loop_name and _check_repeated_call(loop_name, loop_args):
            max_reps = getattr(config, "MAX_REPEATED_TOOL_CALLS", 3)
            logger.warning(
                "handle_tool_call: refusing repeated call to %s (>=%d times in a row this turn)",
                loop_name, max_reps,
            )
            result = None
            error = (
                f"Loop detected: you called {loop_name} with these exact arguments "
                f"{max_reps} times in a row. The result isn't going to change. "
                "Change your approach, try different arguments, or ask the user for guidance."
            )
        else:
            try:
                result, error = execute_tool_call(tool_call)
            except Exception as e:
                logger.error("execute_tool_call raised unexpectedly: %s", e, exc_info=True)
                result, error = None, f"Tool execution raised: {e}"

        # Create and append result message. create_tool_result_message handles
        # None / non-string tool_call_id by coercing to empty string — that
        # still produces an entry in history that pairs with the assistant
        # tool_call (the provider may then reject the empty id, but the
        # structural pairing is preserved and the failure is diagnosable).
        try:
            result_message = create_tool_result_message(result, error, tool_call_id)
            append_to_history_with_count(
                result_message, config.CONVERSATION_HISTORY, count_message_tokens, update_token_usage
            )
        except Exception as e:
            logger.error(
                "Failed to append tool-result message for tool_call_id=%r: %s",
                tool_call_id, e, exc_info=True,
            )

        if error:
            continue

    # Get second response from LLM (token usage is recorded by get_llm_completion via monitor.lib.token_management)
    second_response, error = get_llm_completion()
    if error:
        return "I apologize, but I encountered an error while processing the tool response. Please try again."

    # Token accounting handled by get_llm_completion; no additional update here.

    # Process the response
    result = process_response_by_finish_reason(second_response)

    # If result is None, we need another tool call
    if result is None:
        return handle_tool_call(second_response, _depth=_depth + 1)

    # Update conversation history and return result
    update_conversation_history(
        result,
        "assistant",
        config.CONVERSATION_HISTORY,
        append_func=append_to_history_with_count,
        count_message_tokens_func=count_message_tokens,
        update_token_usage_func=update_token_usage
    )
    return result


def handle(function_call):
    """Handle a function call extracted from user prompt."""
    logger.debug("Handling function call...")

    try:
        # Parse the function call
        logger.debug(f"Processing function_call, type: {type(function_call)}, value: {str(function_call)[:300]}")
        if not isinstance(function_call, dict) and not (hasattr(function_call, 'name') and hasattr(function_call, 'arguments')):
            logger.warning(f"function_call is not a dict or suitable object. type: {type(function_call)} value: {str(function_call)[:300]}")
        function_name, function_args_raw = parse_function_call(function_call)
        print(f"{red}Function name: {function_name}, arguments: {function_args_raw}{reset}")

        # Execute the function
        result, error = execute_function(function_name, function_args_raw)

        # Process and display result
        process_function_result(result, error)

        if error:
            return error

        # Create and append function messages
        function_message, result_message = create_function_result_message(
            function_name, function_args_raw, result
        )
        append_to_history_with_count(
            function_message, config.CONVERSATION_HISTORY, count_message_tokens, update_token_usage
        )
        append_to_history_with_count(
            result_message, config.CONVERSATION_HISTORY, count_message_tokens, update_token_usage
        )

        # Get follow-up response from LLM
        second_response, error = get_llm_completion()
        if error:
            return "I apologize, but I encountered an error processing your request. Please try again."

        # Token accounting handled by get_llm_completion; no additional update here.

        # Process the response
        result = process_response_by_finish_reason(second_response)

        # Update conversation history and return result
        if result is None:
            result = "Ok."
        update_conversation_history(
            result,
            "assistant",
            config.CONVERSATION_HISTORY,
            append_func=append_to_history_with_count,
            count_message_tokens_func=count_message_tokens,
            update_token_usage_func=update_token_usage
        )

        return result

    except Exception as e:
        error_msg = f"Unexpected error in handle: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return error_msg


def create_tool_result_message(result, error, tool_call_id):
    """Create a message for tool execution result.

    This is the single normalization point for tool return values: tools may
    return a dict, a JSON string, or raw text — whatever is natural for them —
    and this function coerces all of them to a string for the model (dicts via
    json.dumps, with a str() fallback). Don't standardize tool return types
    upstream or add a tool-result path that bypasses this; the heterogeneity is
    intentional and reconciled here.

    Ensures content is a JSON-encoded string. Non-string results are JSON-serialized;
    if serialization fails, falls back to str(content). Minimal logging is emitted
    when coercion or fallback occurs.

    Note: No behavior change to message field ordering. Validates presence/type of
    tool_call_id; if missing or None, logs an error and sets it to an empty string
    to satisfy APIs that require a string identifier.
    """
    content = error if error else result

    if not isinstance(content, str):
        try:
            coerced_content = json.dumps(content, ensure_ascii=False)
            logger.debug(f"Coerced non-string tool result into JSON string for tool_call_id={tool_call_id}")
            content = coerced_content
        except Exception as e:
            logger.warning(f"Failed to JSON-encode tool result for tool_call_id={tool_call_id}; falling back to str(): {str(e)}")
            content = str(content)

    # Validate tool_call_id before returning the message
    try:
        original_tool_call_id = tool_call_id
        if tool_call_id is None:
            logger.error("tool_call_id was None when creating tool result message; normalizing to empty string. Upstream must provide non-empty string IDs.")
            tool_call_id = ""
        elif not isinstance(tool_call_id, str):
            # Coerce to string for safety while preserving information
            logger.warning(f"Non-string tool_call_id of type {type(tool_call_id)} encountered; coercing to string via str() for safety")
            try:
                tool_call_id = str(tool_call_id)
            except Exception as ce:
                logger.error(f"Failed coercing non-string tool_call_id={original_tool_call_id!r} to string; defaulting to empty string: {str(ce)}", exc_info=True)
                tool_call_id = ""
        if isinstance(tool_call_id, str) and tool_call_id == "":
            logger.error("Empty tool_call_id after validation/coercion; leaving as empty string to maintain API compatibility. No inference will be attempted; upstream should supply a non-empty ID.")
        elif not tool_call_id:
            logger.error("Falsy tool_call_id after validation/coercion; converting to empty string to maintain API compatibility.")
            tool_call_id = ""
    except Exception as e:
        logger.error(f"Failed validating/coercing tool_call_id; defaulting to empty string: {str(e)}", exc_info=True)
        tool_call_id = ""

    return {"role": "tool", "content": content, "tool_call_id": tool_call_id}


def create_function_result_message(function_name, function_args, result):
    """Create messages for function execution and result"""
    function_message = {
        "role": "assistant",
        "content": "None",
        "function_call": {"name": function_name, "arguments": json.dumps(function_args)},
    }

    result_message = {"role": "function", "name": function_name, "content": result}

    return function_message, result_message


def parse_function_call(function_call):
    """Parse a function call into name and arguments"""
    try:
        logger.debug(f"Processing function_call, type: {type(function_call)}, value: {str(function_call)[:300]}")
        if not isinstance(function_call, dict) and not (hasattr(function_call, 'name') and hasattr(function_call, 'arguments')):
            logger.warning(f"function_call is not a dict or suitable object. type: {type(function_call)} value: {str(function_call)[:300]}")
        function_name = function_call.name
        function_args = function_call.arguments
        logger.debug(f"Parsed function: {function_name}, arguments: {function_args}")
        return function_name, function_args
    except Exception as e:
        logger.error(f"Error parsing function call: {str(e)}", exc_info=True)
        raise


def process_function_result(result, error):
    """Process and display function execution result"""
    output_text = error if error else result
    print(f"{red if error else yellow}{output_text}{reset}")
    return output_text


def execute_function(function_name, function_args_raw):
    """Execute a function with given arguments

    All token counting and estimation is performed using canonical helpers from monitor.lib.token_management as per project policy.
    """
    if function_name not in AVAILABLE_TOOLS:
        logger.error(f"Function {function_name} not found")
        return None, f"Key {function_name} not found in available_functions"

    try:
        # Parse function arguments
        function_args = parse_function_args(function_args_raw)

        # Apply rate limiting for high-token operations (centralized logic)
        if function_name in ["cat_file", "cat_file_range", "list_directory_contents", "modify_source_code"]:
            if function_name in ("cat_file", "cat_file_range") and "path" in function_args:
                try:
                    with open(function_args["path"], "r") as f:
                        content = f.read()
                        estimated_tokens = count_message_tokens({"role": "system", "content": content})
                        if estimated_tokens > LARGE_FILE_TOKEN_THRESHOLD:
                            if rate_limiter.RATE_LIMITER is not None:
                                rate_limiter.RATE_LIMITER.wait_if_needed(estimated_tokens)
                except (FileNotFoundError, PermissionError):
                    pass

            elif function_name == "modify_source_code" and "source_file" in function_args:
                try:
                    with open(function_args["source_file"], "r") as f:
                        content = f.read()
                        estimated_tokens = count_message_tokens({"role": "system", "content": content})
                        if "modification_request" in function_args:
                            estimated_tokens += count_message_tokens(
                                {"role": "user", "content": function_args["modification_request"]}
                            )
                        if rate_limiter.RATE_LIMITER is not None:
                            rate_limiter.RATE_LIMITER.wait_if_needed(estimated_tokens)
                except (FileNotFoundError, PermissionError):
                    pass

        configure_protocol_engine_message_history(config.CONVERSATION_HISTORY)
        result = AVAILABLE_TOOLS[function_name](**function_args)
        logger.debug(f"Function execution result: {result}")

        # Record usage for high-token operations via canonical message token count
        if (
            function_name in ["cat_file", "cat_file_range", "list_directory_contents"]
            and isinstance(result, str)
        ):
            estimated_tokens = count_message_tokens({"role": "system", "content": result})
            if estimated_tokens > LARGE_FILE_TOKEN_THRESHOLD:
                if rate_limiter.RATE_LIMITER is not None:
                    rate_limiter.RATE_LIMITER.add_request(estimated_tokens)
        elif function_name == "modify_source_code":
            # Record substantial token usage for source modifications (still conservatively estimated)
            if rate_limiter.RATE_LIMITER is not None:
                rate_limiter.RATE_LIMITER.add_request(SOURCE_MODIFICATION_TOKEN_ESTIMATE)

        return result, None
    except Exception as e:
        error_msg = f"Error executing {function_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg
