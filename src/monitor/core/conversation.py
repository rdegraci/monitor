import logging
import os
import sys
import time

import litellm

from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit import PromptSession
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.completion import PathCompleter

from monitor import config

from monitor.lib.system_prompt import SYSTEM_PROMPT, build_system_prompt, build_user_prompt_prefix

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
from monitor.lib.tool_profiles import (
    activate_turn_tool_group_leases,
    maybe_apply_explicit_auto_widen,
)
import monitor.lib.subagent_logging as subagent_logging

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


def build_prefixed_user_text(user_text):
    """Prefix user text for model/history submission when needed."""
    prefix = build_user_prompt_prefix()
    text = "" if user_text is None else str(user_text)
    if not prefix:
        return text
    if text.startswith(prefix):
        return text
    return f"{prefix}{text}"


def build_prefixed_model_text(user_text):
    """Return raw built-in commands unchanged; otherwise prefix model-bound text."""
    text = "" if user_text is None else str(user_text)
    if text.startswith(":") or text.startswith("/"):
        return text
    return build_prefixed_user_text(text)


def get_prompt_safety_margin():
    """Compute a conservative safety margin for displayed prompt context remaining."""
    safety_margin = 128
    try:
        if getattr(config, "AGENT", False):
            return 512

        tool_indicators = (
            getattr(config, "TOOLS_ENABLED", False),
            getattr(config, "TOOL_CALLS_ENABLED", False),
            getattr(config, "RESPONSES_API_MODE", False),
            getattr(config, "RESPONSE_API_MODE", False),
            getattr(config, "USE_RESPONSES_API", False),
            getattr(config, "RESPONSES_API", False),
        )
        tool_active = any(bool(flag) for flag in tool_indicators)
        if tool_active:
            safety_margin = 256

        history = getattr(config, "CONVERSATION_HISTORY", None) or []
        recent_history = list(history[-12:])
        tool_heavy = False
        for message in recent_history:
            if not isinstance(message, dict):
                continue

            role = message.get("role", "")
            if role in ("tool", "function"):
                tool_heavy = True
                break

            structured_tool_fields = (
                "tool_calls",
                "function_call",
                "call_id",
                "output",
            )
            if any(field in message and message.get(field) is not None for field in structured_tool_fields):
                tool_heavy = True
                break

            content = message.get("content", None)
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and any(
                        key in item and item.get(key) is not None
                        for key in structured_tool_fields
                    ):
                        tool_heavy = True
                        break
                if tool_heavy:
                    break
    except Exception:
        safety_margin = 128
    return safety_margin


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
    rollback_state = prepare_query_context(user_prompt)

    # Get initial response from LLM (token usage is recorded internally by get_llm_initial_completion/get_llm_completion)
    response, error = get_llm_initial_completion()
    if error:
        rollback_uncommitted_user_turn(rollback_state)
        return ConversationResult.ERROR

    if response is None or not getattr(response, "choices", None):
        rollback_uncommitted_user_turn(rollback_state)
        logger.error("Initial LLM completion returned no choices; rolled back uncommitted user turn.")
        return ConversationResult.ERROR

    # Get response message
    response_message = response.choices[0].message

    # Subagent logging: attempt to record the prompt and reply if agent mode is enabled.
    if getattr(config, "AGENT", False):
        try:
            prompt_text = user_prompt if isinstance(user_prompt, str) else str(user_prompt)
            reply_text = ""
            if hasattr(response_message, "content"):
                reply_text = response_message.content
            else:
                reply_text = str(response_message)
            try:
                subagent_logging.append_interaction(prompt_text=prompt_text, reply_text=reply_text)
            except Exception:
                logger.exception("subagent_logging.append_interaction failed")
        except Exception:
            logger.exception("Failed to prepare subagent logging interaction data")

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
        history = [{"role": "system", "content": build_system_prompt(config.SESSION_ID, getattr(config, "SESSION_ARTIFACTS_PATH", None))}]
        if current_input:
            history.append({"role": "user", "content": build_prefixed_model_text(current_input)})
        history.append({"role": "user", "content": build_prefixed_model_text(directive)})
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

    # Process multiple commands using raw user input so built-in commands are not prefixed.
    # Model-bound content is prefixed later only when it is sent to the model/history.
    from monitor.core.command_processing import (
        process_command,
        process_cd_command,
        handle_exit_command,
    )

    commands = user_input.split(COMMAND_DELIMITER)
    should_exit = False
    for command in commands:
        command = command.strip()
        if not command:
            continue
        if command in ("exit", "/exit"):
            handle_exit_command(command, history_file)
            return True
        if process_command(command, history_file):
            should_exit = True
    return should_exit


def _prompt_with_agent_bridge(session, prompt_text):
    """Prompt while surfacing sub-agent activity (PLAN Phase 3 bridge).

    Flushes completed/streamed agent output ABOVE the prompt (between prompts),
    and — ONLY when sub-agents are active — shows their live status in a bottom
    toolbar. When no agents are active this is byte-identical to a plain
    ``session.prompt(...)``. Any failure degrades to a plain prompt.

    Note: output is flushed *between* prompts, not streamed live *during* one. A
    background live-flush thread was tried but its concurrent printing corrupted
    prompt_toolkit's prompt redraw (the prompt would vanish), so it was removed.
    Agent results still reach you via the next-turn injection and `:agent logs`.
    """
    global _LAST_AGENT_VISIBILITY_SUMMARY
    try:
        from monitor.lib import agent_orchestrator as orch
    except Exception:
        return session.prompt(prompt_text)

    # Flush completed/streamed agent output above the (next) prompt line.
    # When the next turn is a collation/synthesis turn, suppress terminal result
    # replay here — the results will already be folded into the orchestrator's
    # next LLM prefix, and printing them again is noisy.
    try:
        pending_lines = orch.drain_pending_output()
        pending_injections = orch.drain_pending_injections()
        injection_agent_ids = set()
        for notice in pending_injections:
            try:
                if not isinstance(notice, str):
                    continue
                first_quote = notice.find("'")
                second_quote = notice.find("'", first_quote + 1)
                if first_quote == -1 or second_quote == -1:
                    continue
                injection_agent_ids.add(notice[first_quote + 1:second_quote])
            except Exception:
                continue
        for notice in pending_injections:
            config.enqueue_next_llm_prefix(notice)
        if pending_injections:
            config.CURRENT_TURN_IS_COLLATION = True
        for line in pending_lines:
            if config.CURRENT_TURN_IS_COLLATION and isinstance(line, str):
                if any(
                    line.startswith(f"[{agent_id}] ✓") or line.startswith(f"[{agent_id}] ✗")
                    for agent_id in injection_agent_ids
                ):
                    continue
            print(line)
    except Exception:
        logger.debug("agent bridge: drain failed", exc_info=True)

    try:
        active = orch.has_active_agents()
    except Exception:
        active = False
    if not active:
        _LAST_AGENT_VISIBILITY_SUMMARY = None
        return session.prompt(prompt_text)

    try:
        summary = orch.render_visibility_summary()
    except Exception:
        summary = ""
    if summary and summary != _LAST_AGENT_VISIBILITY_SUMMARY:
        print(summary)
        _LAST_AGENT_VISIBILITY_SUMMARY = summary

    # Live status only — no concurrent printing during the prompt. Returning
    # None when there's nothing to show avoids leaving a blank toolbar bar.
    def _toolbar():
        try:
            return orch.render_toolbar() or None
        except Exception:
            return None

    try:
        return session.prompt(prompt_text, bottom_toolbar=_toolbar, refresh_interval=0.5)
    except TypeError:
        # Older prompt_toolkit may reject these kwargs — fall back gracefully.
        return session.prompt(prompt_text)


_LAST_AGENT_VISIBILITY_SUMMARY = None


def _fold_agent_injections_into_prefixes():
    """Main-thread (PLAN 8a): move completed/failed background sub-agent notices
    from the orchestrator's injection queue into ``config.PENDING_LLM_PREFIXES``
    so they ride the next LLM request. Keeping this on the main thread means
    config's prefix list is never mutated from a reader thread. No-op / safe for
    a non-orchestrating session."""
    try:
        from monitor.lib import agent_orchestrator
        notices = agent_orchestrator.drain_pending_injections()
        for notice in notices:
            config.enqueue_next_llm_prefix(notice)
        # Stage 3: a turn that folds in sub-agent results is a collation/synthesis
        # turn — mark it so the orchestrator escalates to ORCHESTRATOR_MODEL for it.
        if notices:
            config.CURRENT_TURN_IS_COLLATION = True
        # Stage 2: fold sub-agent cost/token deltas into this session's totals
        # (F: gauge + U:/T: status line + per-model calibration). Main thread.
        pending_usage = agent_orchestrator.drain_pending_usage()
        for usage in pending_usage:
            config.record_agent_usage(usage)
        try:
            turn_costs = getattr(config, "TURN_COSTS_USD", None)
            if isinstance(turn_costs, list) and turn_costs and pending_usage:
                for usage in pending_usage:
                    cost = usage.get("cost_usd", 0.0) if isinstance(usage, dict) else 0.0
                    if isinstance(cost, (int, float)) and cost > 0:
                        turn_costs[-1] = turn_costs[-1] + float(cost)
                config.TURN_COSTS_USD = turn_costs
        except Exception:
            logger.debug("agent cost fold failed for TURN_COSTS_USD", exc_info=True)
    except Exception:
        logger.debug("agent injection fold failed", exc_info=True)


def _maybe_report_agent_result(user_input):
    """If this monitor is a spawned sub-agent, emit the turn's assistant response
    as a `result` frame so the orchestrator can collect it (PLAN Phase 8b).
    Returns True if a result was reported (used to decide one-shot exit), False
    otherwise. No-op for a normal (non-agent) instance or empty input.
    """
    if not user_input or not str(user_input).strip():
        return False
    try:
        from monitor.lib import agent_reporter
    except Exception:
        return False
    rep = agent_reporter.active()
    if rep is None or not rep.connected:
        return False
    try:
        from monitor.lib.built_in_commands import _last_assistant_response
        summary = _last_assistant_response()
    except Exception:
        summary = None
    if not summary:
        return False
    # Cost telemetry (Stage 2): report the cost/token DELTA since the previous
    # result so the orchestrator can fold this agent's spend into its F: gauge
    # and U:/T: status line. Best-effort — never block the result on telemetry.
    usage = None
    try:
        cost = getattr(config, "SESSION_COST_USD", 0.0) or 0.0
        tokens = getattr(config, "SESSION_TOTAL_TOKENS", 0) or 0
        d_cost = cost - getattr(rep, "reported_cost_usd", 0.0)
        d_tokens = tokens - getattr(rep, "reported_total_tokens", 0)
        if d_cost > 0 or d_tokens > 0:
            usage = {
                "model": getattr(config, "MODEL", "") or "",
                "cost_usd": d_cost,
                "total_tokens": d_tokens,
            }
            rep.reported_cost_usd = cost
            rep.reported_total_tokens = tokens
    except Exception:
        logger.debug("agent cost-telemetry delta failed", exc_info=True)
    rep.result(ok=True, summary=summary, usage=usage)
    rep.status("idle")
    return True


def _agent_is_one_shot():
    """True if this process is a one-shot sub-agent (exits after one task)."""
    try:
        from monitor.lib import agent_reporter
        rep = agent_reporter.active()
        return rep is not None and getattr(rep, "one_shot", False)
    except Exception:
        return False


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
        first_line = _prompt_with_agent_bridge(session, ANSI(prompt))
        logger.debug(f"First line received: {first_line}")

        # Reset terminal colors before printing colored output.
        print(reset)

        # Determine input mode
        # NOTE: determine_input_mode expects first_line first and session last; corrected ordering here.
        input_mode = determine_input_mode(first_line, session)
        logger.debug(f"Input mode determined: {input_mode}")

        # Process input according to mode, passing the existing session so continuations use same PromptSession.
        # Only the final user message line that will be sent to the model is prefixed; command strings stay raw.
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


def prepare_chat_session():
    """Set up the interactive backend shared by the REPL (``chat()``) and the
    full-screen TUI (``--tui``).

    Creates the prompt_toolkit ``PromptSession`` (used for continuation prompts
    and as the ``session`` argument to ``process_input``), initializes chat
    history with the system prompt, stamps the summary clock, and registers the
    conversation query function. Returns ``(session, history_file)``.

    This is the single source of truth for "start an interactive turn loop" so
    the two front-ends never drift. Raises ``RuntimeError`` in server mode —
    interactive backends are disabled there.

    SP-1/SP-2/SP-7: do NOT rebind any module-level SYSTEM_PROMPT here. Call
    sites that need the prompt call ``build_system_prompt()`` directly.
    """
    if getattr(config, "SERVER_MODE", False):
        logger.error("Attempted to start interactive backend while SERVER_MODE is enabled.")
        raise RuntimeError("Interactive chat is disabled in server mode.")

    # Create the PromptSession with additional bindings once per session.
    session = create_prompt_session(additional_bindings=ADDITIONAL_BINDINGS)

    # Initialize chat history
    history_file = config.HISTORY_FILE
    initialize_chat_history(
        config.CONVERSATION_HISTORY,
        lambda message, conversation_history, count_message_tokens, update_token_usage: append_to_history_with_count(
            message, conversation_history, count_message_tokens, update_token_usage
        ),
        build_system_prompt(config.SESSION_ID, getattr(config, "SESSION_ARTIFACTS_PATH", None)),
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

    return session, history_file


def compute_prompt_display():
    """Compute the interactive status/prompt line (the ``monitor <model> ]]``
    prompt with the C:/R:/U:/~T:/P:/L:/H: indicators).

    Extracted from the REPL loop so the ``--tui`` info bar renders the exact
    same status line the REPL shows — one source of truth. Reads live config
    state (history size, token/cost counters, rate limiter), so call it once per
    turn (it tokenizes the full history via ``count_message_tokens``); do NOT
    call it on every UI repaint.

    Returns:
        str: the formatted prompt/status string from ``format_prompt_display``.
    """
    # Use live history count for bug-free prompt display after summarization or history reset:
    tokens_in_history = count_message_tokens(config.CONVERSATION_HISTORY)
    # Prefer MODEL_INPUT_WINDOW (CONTEXT_WINDOW - OUTPUT_WINDOW) as the
    # budget for the C indicator so the displayed remaining matches the
    # input-side gate the send path actually enforces. Fall back to
    # MAX_TOKEN_COUNT when MODEL_INPUT_WINDOW isn't configured.
    input_window = getattr(config, "MODEL_INPUT_WINDOW", None)
    context_budget = input_window if isinstance(input_window, int) and input_window > 0 else config.MAX_TOKEN_COUNT
    context_remaining = context_budget - tokens_in_history
    prompt_safety_margin = get_prompt_safety_margin()
    adjusted_context_remaining = max(0, context_remaining - prompt_safety_margin)
    logger.debug(
        "Prompt safety margin selected: margin=%s context_remaining=%s adjusted_context_remaining=%s",
        prompt_safety_margin,
        context_remaining,
        adjusted_context_remaining,
    )

    rate_remaining = None
    try:
        limiter = getattr(rate_limiter, "RATE_LIMITER", None)
        if limiter is not None:
            limit_value = getattr(limiter, "limit", None)
            current_usage = None
            if hasattr(limiter, "get_current_usage") and callable(getattr(limiter, "get_current_usage")):
                current_usage = limiter.get_current_usage()
            else:
                current_usage = getattr(limiter, "current_usage", None)
            if isinstance(limit_value, (int, float)) and isinstance(current_usage, (int, float)):
                rate_remaining = limit_value - current_usage
    except Exception:
        rate_remaining = None
    # U reads SESSION_TOTAL_TOKENS (pure cumulative, parallel to
    # SESSION_COST_USD) rather than TOTAL_TOKEN_COUNT, which is
    # overwritten by compaction with "current history size" and so
    # would drop dramatically after each summarization. The new
    # counter persists across compaction and only resets on
    # set_model() or :reset_history.
    total_used = getattr(config, "SESSION_TOTAL_TOKENS", None)
    last_used = getattr(config, "LAST_REQUEST_TOKEN_COUNT", None)
    last_used_estimated = getattr(config, "LAST_REQUEST_USED_ESTIMATE", None)
    return format_prompt_display(
        # H reports the count of user/assistant/tool messages — system
        # messages are excluded so a fresh session shows H:0 (rather
        # than H:1 for the system prompt that's in history from startup).
        conversation_count=sum(
            1 for m in config.CONVERSATION_HISTORY
            if isinstance(m, dict) and m.get("role") != "system"
        ),
        tokens_remaining=adjusted_context_remaining,  # adjusted for display safety margin
        context_remaining=adjusted_context_remaining,
        context_budget=context_budget,
        rate_remaining=rate_remaining,
        total_used=total_used,
        last_used=last_used,
        last_used_estimated=last_used_estimated,
        cwd=os.getcwd(),
        model=config.MODEL,  # live config.MODEL value
        extra_history_str="",
        # Retained-history token size (system prompt + kept messages) — the
        # context actually re-sent each request, rendered as the "<n>t" suffix
        # on H:. Already computed above for the C: math; reused here.
        history_tokens=tokens_in_history,
    )


def apply_model_switch_if_needed(last_model):
    """React to a model switch (e.g. via ``:model``): update the live token
    window (``MAX_TOKEN_COUNT``) to the new model's context window and, if the
    existing history now exceeds it, proactively auto-summarize (or warn).

    Shared by the REPL loop (``chat()``) and the ``--tui`` turn loop so both
    front-ends adapt identically. Prints any summary/warning to stdout — callers
    that redirect stdout (the TUI) should call this within that redirect so the
    output lands in the right place. Returns the model to track as ``last_model``
    on the next call (unchanged if no switch occurred).
    """
    if config.MODEL == last_model:
        return last_model

    # Model has changed - update MAX_TOKEN_COUNT to live window, and log this event.
    old_max_token_count = config.MAX_TOKEN_COUNT
    config.MAX_TOKEN_COUNT = config.MODEL_INPUT_WINDOW or config.MODEL_CONTEXT_WINDOW  # fetch latest window size
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
        except Exception:
            logger.error("check_limits failed during model switch handling", exc_info=True)
            print(red + TOKEN_EXCEED_WARNING + reset)
        else:
            if limits and limits.get("should_summarize"):
                try:
                    response = generate_conversation_summary(
                        build_system_prompt(config.SESSION_ID),
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
                            system_prompt=build_system_prompt(config.SESSION_ID),
                            user_input="",
                            conversation_history=config.CONVERSATION_HISTORY,
                            append_func=append_to_history_with_count,
                            logger=logger,
                            config=config,
                        )
                        logger.info(
                            "Conversation history reset (auto-summarized) to comply with context window after model switch."
                        )
                        print(yellow + MODEL_SWITCH_SUMMARY_MESSAGE + reset)
                except Exception:
                    logger.error("Failed to auto-summarize/reset after model switch", exc_info=True)
                    print(red + TOKEN_EXCEED_WARNING + reset)
            else:
                print(red + TOKEN_EXCEED_WARNING + reset)

    return config.MODEL


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
    logger.info("Starting chat loop...")
    logger.info(
        f"Configured with config.MODEL: {config.MODEL}, CONTEXT_WINDOW: {config.MODEL_CONTEXT_WINDOW}"
    )

    # Shared interactive backend setup (also used by the --tui front-end).
    session, history_file = prepare_chat_session()

    # --- Model switch/live token window adaptivity logic:
    last_model = config.MODEL  # Track previous model to detect switches

    # Main chat loop
    while True:
        try:
            # Display prompt and get input

            # React to a live model/context-window switch (shared with --tui).
            last_model = apply_model_switch_if_needed(last_model)

            # Compute the status/prompt line (shared with the --tui info bar).
            prompt = compute_prompt_display()
            user_input = get_input(prompt, session=session)

            # Process input; always flush logs afterward regardless of errors
            exit_flag = False
            try:
                exit_flag = process_input(user_input, history_file, session)
            except Exception as e:
                logger.error(f"Error while processing input: {str(e)}", exc_info=True)
            finally:
                # Write to logs/conversation (always attempt to flush)
                try:
                    flush_logs_and_conversation()
                except Exception:
                    logger.exception("Failed while flushing logs and conversation.")
                # PLAN 8b: if running as a spawned sub-agent, report this turn's
                # assistant response to the orchestrator as a result frame.
                _agent_reported = False
                try:
                    _agent_reported = _maybe_report_agent_result(user_input)
                except Exception:
                    logger.debug("agent result report failed", exc_info=True)

            # PLAN 8f: a one-shot sub-agent exits after its first completed task
            # turn (it has reported its result) so it reaps itself.
            if _agent_reported and _agent_is_one_shot():
                logger.info("One-shot sub-agent completed its task; exiting.")
                break

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


def rollback_uncommitted_user_turn(rollback_state=None) -> bool:
    """Rollback the most recently appended uncommitted user turn.

    This helper removes the exact user message appended for the current turn,
    along with its synchronized per-turn ledgers, when a turn aborts before any
    assistant or tool protocol state is committed. If the stored rollback state
    no longer matches the tail of history, no mutation is applied.

    Args:
        rollback_state (dict | None): Metadata describing the just-appended user
            turn. Expected keys are ``history_length`` and ``message_content``.

    Returns:
        bool: True when the tracked uncommitted user turn was removed,
            otherwise False.
    """
    history = getattr(config, "CONVERSATION_HISTORY", None)
    if not isinstance(history, list) or not history:
        return False

    if not isinstance(rollback_state, dict):
        return False

    expected_length = rollback_state.get("history_length")
    expected_content = rollback_state.get("message_content")
    if not isinstance(expected_length, int) or expected_length <= 0:
        return False

    if len(history) != expected_length:
        logger.info("Skip rollback because conversation history length changed.")
        return False

    last_message = history[-1]
    if not isinstance(last_message, dict) or last_message.get("role") != "user":
        return False

    if last_message.get("content") != expected_content:
        logger.info("Skip rollback because trailing user turn no longer matches tracked state.")
        return False

    history.pop()

    try:
        turn_costs = getattr(config, "TURN_COSTS_USD", None)
        if isinstance(turn_costs, list) and turn_costs:
            turn_costs.pop()
            config.TURN_COSTS_USD = turn_costs
    except Exception:
        logger.debug("Failed to rollback TURN_COSTS_USD for uncommitted user turn", exc_info=True)

    try:
        round_trips = getattr(config, "TURN_ROUND_TRIPS", None)
        if isinstance(round_trips, list) and round_trips:
            round_trips.pop()
            config.TURN_ROUND_TRIPS = round_trips
    except Exception:
        logger.debug("Failed to rollback TURN_ROUND_TRIPS for uncommitted user turn", exc_info=True)

    logger.info("Rolled back tracked uncommitted user turn from conversation history.")
    return True


def prepare_query_context(user_prompt):
    """Prepares and appends the user's prompt to the conversation context.

    This function updates the in-memory conversation history used for LLM calls by:
    1) Optionally prepending any pending LLM prefixes from `config.PENDING_LLM_PREFIXES`
       to the `user_prompt` using the `!<` directive prefix format.
    2) Clearing `config.PENDING_LLM_PREFIXES` after applying them so they are not reused.
    3) Prepending any persisted memory into the conversation history.
    4) Appending the final `user_prompt` into `config.CONVERSATION_HISTORY` via
       `append_conversation_history`, which may also trigger summarization/rotation logic.

    Token counting/usage must use canonical helpers from monitor.lib.token_management
    (enforced by downstream history functions).

    Args:
        user_prompt (str): The raw user prompt text to add to the conversation.

    Returns:
        dict: Rollback metadata for the just-appended user turn.
    """
    # Reset the per-turn collation flag before folding; _fold sets it True iff
    # sub-agent results land on this turn (turn-scoped, like the reasoning override).
    config.CURRENT_TURN_IS_COLLATION = False
    # Seed per-turn temporary tool groups from any short-lived leases carried
    # forward from prior turns, then decrement those leases for future turns.
    try:
        active_tool_groups, expired_tool_groups = activate_turn_tool_group_leases()
        if (
            expired_tool_groups
            and getattr(config, "SHOW_TOOL_PROFILE_NOTICES", True)
        ):
            print(
                f"{yellow}[tools → base:{getattr(config, 'TOOL_PROFILE', 'coding')}] "
                f"expired temporary groups: {', '.join(sorted(expired_tool_groups))}{reset}"
            )
    except Exception:
        logger.exception("Tool-profile lease activation failed; continuing with base profile.")
        active_tool_groups = set()

    # PLAN 8a (async harvest): fold any completed/failed background sub-agent
    # notices into the prefix queue (on the MAIN thread) before it is drained
    # below — so a finished background agent reaches the orchestrator on this
    # turn without anyone having blocked on it.
    _fold_agent_injections_into_prefixes()

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
    try:
        widened_groups = maybe_apply_explicit_auto_widen(
            user_prompt,
            notify=(
                (lambda message: print(f"{yellow}[tools → {message}]{reset}"))
                if getattr(config, "SHOW_TOOL_PROFILE_NOTICES", True)
                else None
            ),
        )
        if widened_groups:
            active_tool_groups = set(getattr(config, "CURRENT_TURN_TOOL_GROUPS", set()) or set())
    except Exception:
        logger.exception("Tool-profile auto-widening failed; continuing with current profile.")

    # Per-turn reasoning override. Always clear the prior turn's override first
    # (so a previous turn's state doesn't leak forward), then apply any explicit
    # inline turn flag from the current request before falling back to the
    # complexity-signal heuristic. The override is read by
    # call_litellm_completion as override-or-default and lasts for every LLM
    # call within this user turn (including tool-chain follow-ups).
    try:
        from monitor.lib.reasoning_heuristic import detect_reasoning_bump
        config.CURRENT_TURN_REASONING_OVERRIDE = None
        stripped_user_prompt = user_prompt.rstrip()
        explicit_adv_flag = " --adv"
        if stripped_user_prompt.endswith(explicit_adv_flag):
            user_prompt = stripped_user_prompt[: -len(explicit_adv_flag)].rstrip()
            config.CURRENT_TURN_REASONING_OVERRIDE = "high"
            logger.info(
                "Applied explicit reasoning override %s for this turn via %s.",
                config.CURRENT_TURN_REASONING_OVERRIDE,
                explicit_adv_flag.strip(),
            )
            print(
                f"{yellow}[reasoning → {config.CURRENT_TURN_REASONING_OVERRIDE}] explicit {explicit_adv_flag.strip()}{reset}"
            )
        else:
            # The configured floor (REASONING_BUMP_EFFORT) is threaded into the
            # heuristic so the bump target — and the gate that decides whether
            # to fire at all — both reflect it. This is what lets a steady
            # "medium" config still bump (to the floored target) on hard turns.
            bump_floor = getattr(config, "REASONING_BUMP_EFFORT", None)
            bump = detect_reasoning_bump(
                user_prompt,
                getattr(config, "REASONING_EFFORT", None),
                bump_floor=bump_floor,
            )
            if bump:
                config.CURRENT_TURN_REASONING_OVERRIDE = bump
                logger.info(
                    "Auto-bumped reasoning effort to %s for this turn (%s).",
                    bump,
                    "matched complexity signals",
                )
                print(f"{yellow}[reasoning → {bump}] matched complexity signals{reset}")
    except Exception:
        logger.exception("Reasoning override detection failed; continuing with default effort.")

    prepend_memory_to_history()
    model_text = build_prefixed_model_text(user_prompt)
    append_conversation_history(
        model_text,
        config.CONVERSATION_HISTORY,
        update_conversation_logs,
        handle_token_limit,  # This will use live config.MAX_TOKEN_COUNT
        check_limits,
        generate_conversation_summary,
        reset_conversation_with_summary,
        build_system_prompt(config.SESSION_ID, getattr(config, "SESSION_ARTIFACTS_PATH", None)),
        config,  # Always pass live config for in-function reads
        post_social_media_summaries,
        logger,
    )
    return {
        "history_length": len(config.CONVERSATION_HISTORY),
        "message_content": model_text,
    }


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
