import logging
import time
import sys
import os

import litellm

from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit import PromptSession
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.completion import PathCompleter

from monitor import config

from monitor.lib.system_prompt import SYSTEM_PROMPT

from monitor.lib.input_modes import (
    handle_single_line,
    handle_multi_command,
    handle_backslash_continuation,
    handle_pipeline_command,
    validate_input,
    format_final_input,
    process_input_mode,
    determine_input_mode,
)

from monitor.core.tooling import (
    execute_tool_call,
    handle_tool_call,
    create_tool_result_message,
    create_function_result_message,
    parse_function_call,
    handle,
    process_function_result,
    execute_function,
)

from monitor.lib.history import (
    append_to_history_with_count,
    update_conversation_history,
    append_conversation_history,
    initialize_chat_history,
    adjust_history_size,
    check_limits,
    generate_conversation_summary,
    reset_conversation_with_summary,
)

# Enforce canonical token counting and usage through lib.token_management
# All token estimation and rate limiting must use helpers from monitor.lib.token_management
from monitor.lib.token_management import (
    count_message_tokens,  # Canonical message token counter
    update_token_usage,  # Canonical token usage updater
)

from monitor.core.llm import (
    get_llm_completion,
    get_llm_initial_completion,
    process_response_by_finish_reason,
    process_direct_response,
    process_response_by_type,
    determine_response_type,
    extract_tool_calls,
)

from monitor.core.query_service import register_query_function
from monitor.lib.macros import add_macro_definition
from monitor.lib.external_services import (
    send_artifact,
    send_twitter_message,
    send_twitch_message_command,
    send_linkedin_message,
    joke_for_twitch,
    send_file_to_indexing_service,
    send_query_to_indexing_service,
)
from monitor.lib.summarizers import (
    summarize_conversation_questionnaire_for_twitch,
    summarize_conversation_for_linkedin,
    summarize_conversation_for_twitter,
    summarize_conversation_for_twitch,
)
from monitor.lib.colors import blue, red, yellow, reset
from monitor.lib.redis_utils import prepend_memory_to_history

logger = logging.getLogger(__name__)

from monitor.lib.built_in_commands import clear_screen
from monitor.lib.lexer import create_prompt_session

# Remove: from monitor.lib.rate_limiter import estimate_token_count
# All token counting now enforced via lib.token_management
from monitor.lib.display_output import format_prompt_display
from monitor.lib import rate_limiter

from monitor.lib.keyboard import (
    ctrl_left_handler,
    ctrl_right_handler,
    f10_voice_handler,
)

from enum import Enum


class InputMode(Enum):
    SINGLE_LINE = "single_line"
    MULTI_LINE = "multi_line"
    PIPELINE = "pipeline"
    BACKSLASH_CONTINUATION = "backslash_continuation"


class ResponseType(Enum):
    DIRECT = "direct"
    TOOL_CALL = "tool_call"
    FUNCTION_CALL = "function_call"


class ConversationResult(Enum):
    """
    Enum representing conversation command results and statuses.
    Use this for outcome/status values such as SUCCESS, ERROR, RESET.
    """

    SUCCESS = "success"
    ERROR = "error"
    RESET = "reset"


TOTAL_CONVERSATION_HISTORY_COUNT = 0

# Define additional key bindings using the handler functions
# For f10, we use a lambda to pass config as an additional argument to f10_voice_handler,
# because prompt_toolkit expects key binding functions to accept (event) only.
ADDITIONAL_BINDINGS = {
    "c-left": ctrl_left_handler,
    "c-right": ctrl_right_handler,
    "f10": lambda event: f10_voice_handler(event, config),
}

# Constants
DEFAULT_PROMPT = "> "
CONTINUATION_PROMPT = "... "
COMMAND_DELIMITER = ";;;"
MACRO_STARTER = "<"
JOKE_INTERVAL = 20
DEFAULT_PAGE_SIZE = 10
DASH_LINE_LENGTH = 40
NEXT_COMMAND = "n"
PREVIOUS_COMMAND = "p"
QUIT_COMMAND = "q"
NAVIGATION_INSTRUCTIONS = f"Press '{NEXT_COMMAND}' for next, '{PREVIOUS_COMMAND}' for previous, '{QUIT_COMMAND}' to quit"
COMMAND_PROMPT = "Command: "
NO_HISTORY_MESSAGE = "No conversation history to display."
HISTORY_DISPLAY_FORMAT = "Showing items {start} to {end} of {total}"
HISTORY_ITEM_FORMAT = "{index}: {item}"
PIPELINE_FAILURE_FORMAT = "Pipeline step {step} failed: {error}"
USER_LOG_FORMAT = "User: {input}\n"
MODEL_SWITCH_SUMMARY_MESSAGE = "Conversation reset/autosummarized to fit new model window."
TOKEN_EXCEED_WARNING = "Warning: Token usage exceeds the new model context window. Please summarize or reset."


def post_social_media_summaries():
    """Generate and post summaries to social media (robust error handling per platform)"""

    if config.SUMMARY_TWITCH is True:
        # Fetch live model from monitor.config to ensure summary logic is always up to date
        summary_twitch = summarize_conversation_questionnaire_for_twitch(
            config.CONVERSATION_HISTORY, config.MODEL
        )
        if not isinstance(summary_twitch, str) or not summary_twitch.strip():
            logger.info("No Twitch questions generated; skipping post to Twitch.")
            print(yellow + "No Twitch questions generated; skipping post to Twitch." + reset)
            return
        try:
            send_twitch_message_command(summary_twitch)
        except Exception as e:
            logger.error("Unable to post questions to Twitch.", exc_info=True)
            print(
                red
                + "Twitch posting failed: Unable to post questions to Twitch. Please check your network connection and Twitch credentials/configuration."
                + reset
            )
        else:
            print(yellow + "Successfully posted Twitch questions." + reset)

    if config.SUMMARY_LINKEDIN is True:
        summary_linkedin = summarize_conversation_for_linkedin(
            config.CONVERSATION_HISTORY, config.MODEL
        )
        if not isinstance(summary_linkedin, str) or not summary_linkedin.strip():
            logger.info("No LinkedIn summary generated; skipping post to LinkedIn.")
            print(yellow + "No LinkedIn summary generated; skipping post to LinkedIn." + reset)
            return
        try:
            send_linkedin_message(summary_linkedin)
        except Exception as e:
            logger.error("Failed to post summary to LinkedIn.", exc_info=True)
            print(
                red
                + "LinkedIn posting failed: Unable to post summary to LinkedIn. Please check your network connection and LinkedIn credentials/configuration."
                + reset
            )
        else:
            print(yellow + "Successfully posted summary to LinkedIn." + reset)

    if config.SUMMARY_TWITTER is True:
        summary_twitter = summarize_conversation_for_twitter(
            config.CONVERSATION_HISTORY, config.MODEL
        )
        if not isinstance(summary_twitter, str) or not summary_twitter.strip():
            logger.info("No Twitter summary generated; skipping post to Twitter.")
            print(yellow + "No Twitter summary generated; skipping post to Twitter." + reset)
            return
        try:
            send_twitter_message(summary_twitter)
        except Exception as e:
            logger.error("Failed to post summary to Twitter.", exc_info=True)
            print(
                red
                + "Twitter posting failed: Unable to post summary to Twitter. Please check your network connection and Twitter credentials/configuration."
                + reset
            )
        else:
            print(yellow + "Successfully posted summary to Twitter." + reset)


def update_conversation_logs(user_input, conversation_log_file=config.CONVERSATION_LOG_FILE):
    """Update conversation logs with user input"""
    if (config.CONVERSATION_LOG_FILE is not None) and not config.CONVERSATION_LOG_FILE.closed:
        config.CONVERSATION_LOG_FILE.write(USER_LOG_FORMAT.format(input=user_input))


def query(user_prompt):
    """
    Process a user query and return the response after executing necessary commands.
    Uses config.last_summary_time for summary time management.
    All token counting/usage must use canonical helpers from monitor.lib.token_management.
    Returns:
        ConversationResult: Use ConversationResult Enum for result statuses.
    """
    logger.debug("Processing user query...")

    # Prepare the conversation context
    prepare_query_context(user_prompt)

    # Get initial response from LLM (token usage is recorded internally by get_llm_initial_completion/get_llm_completion)
    response, error = get_llm_initial_completion()
    if error:
        return ConversationResult.ERROR

    # Get response message
    response_message = response.choices[0].message

    # Determine how to handle the response
    return process_response_by_type(
        response_type := determine_response_type(response_message), response, response_message
    )


def process_pipeline_directives(directives):
    """
    Run pipeline steps in sequence, enforcing all token counting/limit logic via lib.token_management.
    Deprecated: Any use of token estimation outside lib.token_management is forbidden.
    Returns:
        result (str): Final pipeline output or ConversationResult Enum value upon error.
    """
    current_input = None
    for idx, directive in enumerate(directives):
        history = [{"role": "system", "content": SYSTEM_PROMPT}]
        if current_input:
            history.append({"role": "user", "content": current_input})
        history.append({"role": "user", "content": directive})
        # 1. Canonical token count using token_management
        # All token estimation and usage logic must call count_message_tokens
        estimated_tokens = count_message_tokens(history)
        # Note: Rate limiting logic must also use only update_token_usage if applicable; token usage is already recorded by get_llm_completion.
        # 2. Enforce rate limit BEFORE making LLM call
        # NOTE: All token accounting must flow through canonical helpers; if custom rate limiting is required,
        # ensure it relies on the usage recorded by get_llm_completion
        # 3. Make the LLM call (token usage is recorded internally by get_llm_completion)
        response, error = get_llm_completion(history)
        if error:
            print(PIPELINE_FAILURE_FORMAT.format(step=idx + 1, error=error))
            return ConversationResult.ERROR
        # Token usage already recorded by get_llm_completion; avoid duplicate accounting.
        current_input = response.choices[0].message.content
    return current_input


def process_input(user_input, history_file, session):
    """
    Process user input and return exit flag.

    Args:
        user_input (str): The input string provided by the user.
        history_file (file-like): File handle to write history if needed.
        session (PromptSession): The prompt_toolkit session to use for continuation prompts.

    Returns:
        bool: True if the caller should exit the main loop, False otherwise.
    """
    if user_input == "":
        return False

    logger.debug("User input: {}".format(user_input))

    # Handle macro definitions
    if user_input.startswith(MACRO_STARTER):
        add_macro_definition(user_input)
        return False

    # Special handling for pipeline input mode
    # NOTE: determine_input_mode and process_input_mode expect the first argument to be the input string (first_line),
    #       with the session passed as the last argument. Correct argument ordering is applied here.
    if determine_input_mode(user_input, session) == InputMode.PIPELINE.value:
        # Gather directives using process_input_mode and handle_pipeline_command
        lines = process_input_mode(user_input, InputMode.PIPELINE.value, session)
        if not lines:
            return False
        final_output = process_pipeline_directives(lines)
        display_query_result(
            final_output,
            update_history_count=lambda: setattr(
                config, "TOTAL_CONVERSATION_HISTORY_COUNT", config.TOTAL_CONVERSATION_HISTORY_COUNT + 2
            ),
        )
        return False

    # Process multiple commands
    from monitor.core.command_processing import (
        process_command,
        process_cd_command,
        handle_exit_command,
    )

    commands = user_input.split(COMMAND_DELIMITER)
    should_exit = False
    for command in commands:
        if process_command(command, history_file):
            should_exit = True
    return should_exit


def get_input(prompt=DEFAULT_PROMPT, continuation_prompt=CONTINUATION_PROMPT, session=None):
    """
    Capture and process user input using prompt_toolkit with custom lexer for red highlighting after 120 characters.

    Args:
        prompt (str): The main prompt string to display.
        continuation_prompt (str): The prompt used for continuation lines.
        session (PromptSession): The prompt_toolkit session to use for the prompt. If None, a new session will be created
            by the caller and should be passed in; this function expects a session parameter.

    Returns:
        str: The final formatted input string, or empty string on EOF/interrupt/error.
    """
    logger.debug("Starting input capture with prompt_toolkit...")
    try:
        if session is None:
            raise ValueError("A PromptSession 'session' must be provided to get_input().")

        # Use the provided prompt_toolkit session
        first_line = session.prompt(ANSI(prompt))
        logger.debug(f"First line received: {first_line}")

        # Reset terminal colors before printing colored output.
        print(reset)

        # Determine input mode
        # NOTE: determine_input_mode expects first_line first and session last; corrected ordering here.
        input_mode = determine_input_mode(first_line, session)
        logger.debug(f"Input mode determined: {input_mode}")

        # Process input according to mode, passing the existing session so continuations use same PromptSession
        # process_input_mode expects (first_line, input_mode, session)
        lines = process_input_mode(first_line, input_mode, session)

        # Validate collected input
        if not validate_input(lines):
            logger.error("Input validation failed")
            return ""

        # Format and return final input
        final_input = format_final_input(lines)
        logger.debug(f"Final formatted input: {final_input}")
        return final_input

    except EOFError:
        logger.debug("EOFError received in main input loop")
        print()  # Print newline for cleaner output
        return ""
    except KeyboardInterrupt:
        logger.debug("KeyboardInterrupt received in input loop")
        print()  # Print newline for cleaner output
        return ""
    except Exception as e:
        logger.error(f"Unexpected error in input processing: {str(e)}", exc_info=True)
        return ""


def flush_logs_and_conversation():
    if config.CONVERSATION_LOG_FILE:
        config.CONVERSATION_LOG_FILE.flush()
    for handler in logging.getLogger().handlers:
        if hasattr(handler, "flush"):
            try:
                handler.flush()
            except Exception:
                pass
        # Force OS-level flush for file handlers
        if hasattr(handler, "stream") and hasattr(handler.stream, "fileno"):
            try:
                import os

                os.fsync(handler.stream.fileno())
            except Exception:
                pass


def chat():
    """
    Main loop for interactive chatting with the system.

    This function enforces that interactive chat is disabled in server mode.
    If config.SERVER_MODE is True, this function will log an error and raise RuntimeError.

    Uses config.last_summary_time for managing conversation summaries.
    All token counting/usage must use canonical helpers from monitor.lib.token_management.

    Returns:
        ConversationResult: Use ConversationResult Enum for result statuses.
    """
    # Enforce server-mode restriction at the very start of the interactive chat.
    if getattr(config, "SERVER_MODE", False):
        logger.error("Attempted to start interactive chat while SERVER_MODE is enabled.")
        raise RuntimeError("Interactive chat is disabled in server mode.")

    logger.info("Starting chat loop...")
    logger.info(
        f"Configured with config.MODEL: {config.MODEL}, CONTEXT_WINDOW: {config.MODEL_CONTEXT_WINDOW}"
    )

    # Create the PromptSession with additional bindings once per chat session
    session = create_prompt_session(additional_bindings=ADDITIONAL_BINDINGS)

    global SYSTEM_PROMPT
    SYSTEM_PROMPT += f"\nCurrent session ID: {config.SESSION_ID}. Use this SESSION_ID in all todo tool calls."

    # Initialize chat history
    history_file = config.HISTORY_FILE
    initialize_chat_history(
        config.CONVERSATION_HISTORY,
        lambda message, conversation_history, count_message_tokens, update_token_usage: append_to_history_with_count(
            message, conversation_history, count_message_tokens, update_token_usage
        ),
        SYSTEM_PROMPT,
        config.HISTORY_FILE,
        logger,
        config,
        count_message_tokens,
        update_token_usage,
    )

    config.last_summary_time = time.time()

    def session_query(user_prompt):
        response = query(user_prompt)
        return response

    register_query_function(session_query)

    # --- Model switch/live token window adaptivity logic:
    last_model = config.MODEL  # Track previous model to detect switches

    # Main chat loop
    while True:
        try:
            # Display prompt and get input

            # Check for live model/context window update after a model switch:
            if config.MODEL != last_model:
                # Model has changed - update MAX_TOKEN_COUNT to live window, and log this event.
                old_max_token_count = config.MAX_TOKEN_COUNT
                config.MAX_TOKEN_COUNT = config.MODEL_CONTEXT_WINDOW  # fetch latest window size
                logger.info(
                    f"Model switched: new config.MODEL: {config.MODEL}, context_window: {config.MODEL_CONTEXT_WINDOW}, MAX_TOKEN_COUNT updated from {old_max_token_count} to {config.MAX_TOKEN_COUNT}"
                )

                # After switch, compute tokens_in_history using canonical counter and derive tokens_remaining.
                tokens_in_history = count_message_tokens(config.CONVERSATION_HISTORY)
                tokens_remaining = config.MAX_TOKEN_COUNT - tokens_in_history
                logger.info(
                    f"Tokens in history after model switch: {tokens_in_history}; tokens remaining: {tokens_remaining}"
                )

                # If token count now exceeds window, auto-summarize or alert user. (this is proactive behavior)
                if tokens_in_history > config.MAX_TOKEN_COUNT:
                    logger.warning(
                        f"tokens_in_history ({tokens_in_history}) exceeds new MAX_TOKEN_COUNT ({config.MAX_TOKEN_COUNT}) after model switch, triggering summarization or alert..."
                    )

                    # Use check_limits to determine whether summarization should occur
                    try:
                        limits = check_limits(
                            tokens_in_history,
                            config.MAX_TOKEN_COUNT,
                            config.CONVERSATION_MAX_SIZE,
                            config.CONVERSATION_HISTORY,
                            config.SUMMARIZATION_CONFIG,
                            logger,
                            config,
                            time_since_last_summary=0,
                        )
                    except Exception as e:
                        logger.error("check_limits failed during model switch handling", exc_info=True)
                        print(red + TOKEN_EXCEED_WARNING + reset)
                    else:
                        if limits and limits.get("should_summarize"):
                            try:
                                response = generate_conversation_summary(
                                    SYSTEM_PROMPT,
                                    config.CONVERSATION_HISTORY,
                                    config.SUMMARIZATION_CONFIG,
                                    config.MODEL,
                                    litellm.completion,
                                    count_message_tokens,
                                    rate_limiter.RATE_LIMITER,
                                    logger,
                                    config,
                                )
                                logger.debug("Received summary response for auto-summarization during model switch")
                                summary_text = None
                                if hasattr(response, "choices") and len(response.choices) > 0 and hasattr(
                                    response.choices[0], "message"
                                ):
                                    summary_text = response.choices[0].message.content
                                if not isinstance(summary_text, str) or not summary_text.strip():
                                    logger.error(
                                        "generate_conversation_summary returned empty or invalid summary during model switch handling"
                                    )
                                    print(red + TOKEN_EXCEED_WARNING + reset)
                                else:
                                    reset_conversation_with_summary(
                                        summary=summary_text,
                                        system_prompt=SYSTEM_PROMPT,
                                        user_input="",
                                        conversation_history=config.CONVERSATION_HISTORY,
                                        append_func=append_to_history_with_count,
                                        logger=logger,
                                        config=config,
                                    )
                                    logger.info(
                                        f"Conversation history reset (auto-summarized) to comply with context window after model switch."
                                    )
                                    print(yellow + MODEL_SWITCH_SUMMARY_MESSAGE + reset)
                            except Exception as e:
                                logger.error("Failed to auto-summarize/reset after model switch", exc_info=True)
                                print(red + TOKEN_EXCEED_WARNING + reset)
                        else:
                            print(red + TOKEN_EXCEED_WARNING + reset)
                # Update last_model to reflect switch has been handled
                last_model = config.MODEL

            # Use live history count for bug-free prompt display after summarization or history reset:
            tokens_in_history = count_message_tokens(config.CONVERSATION_HISTORY)
            context_remaining = config.MAX_TOKEN_COUNT - tokens_in_history
            rate_remaining = None
            try:
                limiter = getattr(rate_limiter, "RATE_LIMITER", None)
                if limiter is not None:
                    limit_value = getattr(limiter, "limit", None)
                    current_usage = None
                    used_get_current_usage = False
                    if hasattr(limiter, "get_current_usage") and callable(getattr(limiter, "get_current_usage")):
                        current_usage = limiter.get_current_usage()
                        used_get_current_usage = True
                    else:
                        current_usage = getattr(limiter, "current_usage", None)
                    if isinstance(limit_value, (int, float)) and isinstance(current_usage, (int, float)):
                        rate_remaining = limit_value - current_usage
                    try:
                        logger.info(
                            "RateLimiter introspection: limiter_type=%s limit=%r current_usage=%r current_usage_source=%s rate_remaining=%r",
                            type(limiter),
                            limit_value,
                            current_usage,
                            "get_current_usage" if used_get_current_usage else "current_usage_attr",
                            rate_remaining,
                        )
                    except Exception:
                        pass
            except Exception:
                rate_remaining = None
            total_used = getattr(config, "TOTAL_TOKEN_COUNT", None)
            last_used = getattr(config, "LAST_REQUEST_TOKEN_COUNT", None)
            last_used_estimated = getattr(config, "LAST_REQUEST_USED_ESTIMATE", None)
            prompt = format_prompt_display(
                conversation_count=len(config.CONVERSATION_HISTORY),  # IMPORTANT: Use live state for accuracy
                tokens_remaining=context_remaining,  # live calculation based on current history
                context_remaining=context_remaining,
                rate_remaining=rate_remaining,
                total_used=total_used,
                last_used=last_used,
                last_used_estimated=last_used_estimated,
                cwd=os.getcwd(),
                model=config.MODEL,  # live config.MODEL value
                extra_history_str=f"({len(config.CONVERSATION_HISTORY) - config.CONVERSATION_MAX_SIZE})",
            )
            user_input = get_input(prompt, session=session)

            # Process input and check for exit
            exit_flag = process_input(user_input, history_file, session)

            # Write to logs/conversation
            flush_logs_and_conversation()

            if not exit_flag:
                continue
            else:
                break

        except Exception as e:
            logger.error(f"Error in chat loop: {str(e)}", exc_info=True)
            continue


def handle_periodic_twitch_joke(total_conversation_history_count=TOTAL_CONVERSATION_HISTORY_COUNT):
    """Handle periodic Twitch joke posting"""
    if (total_conversation_history_count > 0) and (
        total_conversation_history_count % JOKE_INTERVAL == 0
    ):
        joke_for_twitch()


def handle_token_limit(max_token_count=None, total_token_count=None):
    # Always fetch live config values for token management to avoid staleness
    new_token_count = config.MAX_TOKEN_COUNT  # live config.MAX_TOKEN_COUNT read
    return new_token_count


def prepare_query_context(user_prompt):
    """Prepares and appends the user's prompt to the conversation context.

    This function updates the in-memory conversation history used for LLM calls by:
    1) Optionally prepending any pending LLM prefixes from `config.PENDING_LLM_PREFIXES`
       to the `user_prompt` using the `!<` directive prefix format.
    2) Clearing `config.PENDING_LLM_PREFIXES` after applying them so they are not reused.
    3) Prepending any persisted memory into the conversation history.
    4) Appending the final `user_prompt` into `config.CONVERSATION_HISTORY` via
       `append_conversation_history`, which may also trigger summarization/rotation logic.

    Token counting/usage must use canonical helpers from `monitor.lib.token_management`
    (enforced by downstream history functions).

    Args:
        user_prompt (str): The raw user prompt text to add to the conversation.

    Returns:
        None: This function mutates `config.CONVERSATION_HISTORY` and summary timing state.
    """
    pending_prefixes = getattr(config, "PENDING_LLM_PREFIXES", None)
    if pending_prefixes:
        notice = "\n".join(str(p) for p in pending_prefixes if p is not None)
        if notice.strip():
            user_prompt = f"!<{notice}\n\n{user_prompt}"
        elif not str(user_prompt).startswith("!<"):
            user_prompt = f"!<{user_prompt}"
        try:
            pending_prefixes.clear()
        except Exception:
            try:
                setattr(config, "PENDING_LLM_PREFIXES", [])
            except Exception:
                pass
    logger.debug("Preparing query context...")
    prepend_memory_to_history()
    append_conversation_history(
        user_prompt,
        config.CONVERSATION_HISTORY,
        update_conversation_logs,
        handle_token_limit,  # This will use live config.MAX_TOKEN_COUNT
        check_limits,
        generate_conversation_summary,
        reset_conversation_with_summary,
        SYSTEM_PROMPT,
        config,  # Always pass live config for in-function reads
        post_social_media_summaries,
        logger,
    )
    # No return value needed; config.last_summary_time is updated by append_conversation_history.


def conversation_history_command(arg, page_size=DEFAULT_PAGE_SIZE):
    """Display conversation history with pagination."""

    logger.debug(f"Scrolling conversation history with page size: {page_size}")
    array = config.CONVERSATION_HISTORY
    index = 0
    array_length = len(array)

    if array_length == 0:
        logger.info(NO_HISTORY_MESSAGE)
        print(NO_HISTORY_MESSAGE)
        return

    while True:
        clear_screen()
        logger.debug(
            f"Displaying items {index + 1} to {min(index + page_size, array_length)} of {array_length}"
        )

        print(HISTORY_DISPLAY_FORMAT.format(start=index + 1, end=min(index + page_size, array_length), total=array_length))
        print("-" * DASH_LINE_LENGTH)
        for i in range(index, min(index + page_size, array_length)):
            print(HISTORY_ITEM_FORMAT.format(index=i + 1, item=array[i]))

        print("-" * DASH_LINE_LENGTH)
        print(NAVIGATION_INSTRUCTIONS)

        command = input(COMMAND_PROMPT).strip().lower()
        logger.debug(f"User entered command: {command}")

        if command == NEXT_COMMAND and index + page_size < array_length:
            index += page_size
            logger.debug(f"Moving to next page, new index: {index}")
        elif command == PREVIOUS_COMMAND and index - page_size >= 0:
            index -= page_size
            logger.debug(f"Moving to previous page, new index: {index}")
        elif command == QUIT_COMMAND:
            logger.debug("Exiting conversation history view")
            break
        else:
            logger.warning(f"Invalid command or navigation limit reached: {command}")
            input("Press Enter to continue...")


# End of file
