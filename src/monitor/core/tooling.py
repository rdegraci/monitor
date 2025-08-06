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
    """
    logger.debug(f"Processing tool_call, type: {type(tool_call)}, value: {str(tool_call)[:300]}")
    function_args_raw = tool_call["function"]["arguments"]
    function_name = tool_call["function"]["name"]
    logger.debug(f"Executing function: {function_name}, arguments: {function_args_raw}")

    if function_name not in AVAILABLE_TOOLS:
        logger.error(f"Function {function_name} not found")
        return None, f"Key {function_name} not found in available_functions"

    try:
        # Parse function arguments
        function_args = parse_function_args(function_args_raw)

        # Apply rate limiting for high-token operations using centralized API
        if function_name in ["cat_file", "list_directory_contents", "create_file"]:
            if function_name == "cat_file" and "path" in function_args:
                # Use count_message_tokens for accurate estimation
                try:
                    with open(function_args["path"], "r") as f:
                        content = f.read()
                        estimated_tokens = count_message_tokens({"role": "system", "content": content})
                        if estimated_tokens > LARGE_FILE_TOKEN_THRESHOLD:
                            rate_limiter.RATE_LIMITER.wait_if_needed(estimated_tokens)
                except (FileNotFoundError, PermissionError):
                    pass

            elif function_name == "list_directory_contents" and "path" in function_args:
                if function_args.get("recursive", False):
                    # Still use conservative estimate for recursion
                    rate_limiter.RATE_LIMITER.wait_if_needed(RECURSIVE_DIR_TOKEN_ESTIMATE)

        result = AVAILABLE_TOOLS[function_name](**function_args)
        logger.debug(f"Result: {result}")

        # Record usage for high-token operations using canonical counting API
        if (
            function_name in ["cat_file", "list_directory_contents"]
            and isinstance(result, str)
        ):
            estimated_tokens = count_message_tokens({"role": "system", "content": result})
            if estimated_tokens > LARGE_FILE_TOKEN_THRESHOLD:
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


def handle_tool_call(response):
    """Orchestrate the handling of tool calls from LLM response

    All token counting and estimation logic is routed through lib.token_management per project policy.
    """

    from monitor.core.conversation import (
        extract_tool_calls,
        append_to_history_with_count,
        get_llm_completion,
        process_response_by_finish_reason,
        update_conversation_history,
    )

    logger.debug("Handling tool call...")

    # Extract tool calls
    tool_calls = extract_tool_calls(response)

    # Process each tool call
    for tool_call in tool_calls:
        logger.debug(f"Processing tool_call, type: {type(tool_call)}, value: {str(tool_call)[:300]}")
        # Execute the tool
        result, error = execute_tool_call(tool_call)

        # Create and append result message using the 4-argument signature
        result_message = create_tool_result_message(result, error, tool_call["id"])
        append_to_history_with_count(
            result_message, config.CONVERSATION_HISTORY, count_message_tokens, update_token_usage
        )

        if error:
            continue

    # Get second response from LLM
    second_response, error = get_llm_completion()
    if error:
        return "I apologize, but I encountered an error while processing the tool response. Please try again."

    # Update token count: handled by append_to_history_with_count for each message
    config.TOTAL_TOKEN_COUNT += second_response.usage.total_tokens

    # Process the response
    result = process_response_by_finish_reason(second_response)

    # If result is None, we need another tool call
    if result is None:
        return handle_tool_call(second_response)

    # Update conversation history and return result
    update_conversation_history(
        result,
        "assistant",
        config.CONVERSATION_HISTORY,
        lambda msg, conv_hist: append_to_history_with_count(
            msg, conv_hist, count_message_tokens, update_token_usage
        ),
        count_message_tokens,
        update_token_usage
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

        # Update token count
        config.TOTAL_TOKEN_COUNT += second_response.usage.total_tokens

        # Process the response
        result = process_response_by_finish_reason(second_response)

        # Update conversation history and return result
        if result is None:
            result = "Ok."
        update_conversation_history(
            result,
            "assistant",
            config.CONVERSATION_HISTORY,
            lambda msg, conv_hist: append_to_history_with_count(
                msg, conv_hist, count_message_tokens, update_token_usage
            ),
            count_message_tokens,
            update_token_usage
        )

        return result

    except Exception as e:
        error_msg = f"Unexpected error in handle: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return error_msg


def create_tool_result_message(result, error, tool_call_id):
    """Create a message for tool execution result.

    Content must be a JSON string. This function does not perform any type coercion or warnings.
    """
    content = error if error else result

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
        if function_name in ["cat_file", "list_directory_contents", "modify_source_code"]:
            if function_name == "cat_file" and "path" in function_args:
                try:
                    with open(function_args["path"], "r") as f:
                        content = f.read()
                        estimated_tokens = count_message_tokens({"role": "system", "content": content})
                        if estimated_tokens > LARGE_FILE_TOKEN_THRESHOLD:
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
                        rate_limiter.RATE_LIMITER.wait_if_needed(estimated_tokens)
                except (FileNotFoundError, PermissionError):
                    pass

        configure_protocol_engine_message_history(config.CONVERSATION_HISTORY)
        result = AVAILABLE_TOOLS[function_name](**function_args)
        logger.debug(f"Function execution result: {result}")

        # Record usage for high-token operations via canonical message token count
        if (
            function_name in ["cat_file", "list_directory_contents"]
            and isinstance(result, str)
        ):
            estimated_tokens = count_message_tokens({"role": "system", "content": result})
            if estimated_tokens > LARGE_FILE_TOKEN_THRESHOLD:
                rate_limiter.RATE_LIMITER.add_request(estimated_tokens)
        elif function_name == "modify_source_code":
            # Record substantial token usage for source modifications (still conservatively estimated)
            rate_limiter.RATE_LIMITER.add_request(SOURCE_MODIFICATION_TOKEN_ESTIMATE)

        return result, None
    except Exception as e:
        error_msg = f"Error executing {function_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg
