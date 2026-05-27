import readline
import logging
import signal
from monitor import config
import monitor.core.conversation

logger = logging.getLogger(__name__)

from monitor.core.commands import (
    is_interactive_command,
    is_non_interactive_command,
    execute_non_interactive_command,
    execute_interactive_command,
    is_internal_command,
    execute_internal_command
)

from monitor.core.conversation import prepare_query_context
from monitor.lib.macros import MACRO_VALUES
from monitor.lib.external_services import send_artifact

from monitor.lib.macro_utils import recursive_macro_expand
from monitor.lib.built_ins_utils import (
    is_built_in_function,
    execute_built_in_function,
)
from monitor.lib.built_in_commands import handle_cd_command
from monitor.lib.display_output import display_query_result
from monitor.lib.colors import yellow, reset

from dataclasses import dataclass
from typing import Optional
from enum import Enum, auto


class CommandType(Enum):
    LLM = "llm"
    MACRO = "macro"
    CD = "cd"
    BUILT_IN = "built_in"
    INTERNAL = "internal"
    INTERACTIVE = "interactive"
    NON_INTERACTIVE = "non_interactive"
    ERROR = "error"
    EXIT = "exit"
    UNSUPPORTED = "unsupported"
    EMPTY = "empty"
    FILE_IO = "file_io"
    NETWORK = "network"
    DB_QUERY = "db_query"
    SCRIPT = "script"
    PLUGIN = "plugin"
    PERMISSION = "permission"
    UI_COMMAND = "ui_command"
    # For extensibility - add more as needed


@dataclass
class CommandResult:
    """Structured result returned by evaluate_command()."""
    output: Optional[str] = None  # textual result or None
    exit_requested: bool = False  # True if the command was an exit request
    error: Optional[str] = None  # error message, if any
    command_type: CommandType = CommandType.LLM  # Use CommandType Enum


def evaluate_command(command: str) -> CommandResult:
    """
    Evaluate a single command string and return a side-effect-free CommandResult.
    This function performs the same semantic analysis that the REPL previously
    executed inside process_command() but purposefully avoids user-visible side
    effects such as printing to stdout, writing files, or mutating readline
    history. It is therefore safe to call from both interactive and HTTP
    contexts.

    IMPORTANT:
    - This routine assumes the command has already been macro-expanded (if
      desired) by the caller. It will NOT perform macro expansion or execute
      side effects such as calling query() or changing directories.
    """
    try:
        if not command or not command.strip():
            return CommandResult(command_type=CommandType.EMPTY)

        # Detect exit commands early (no side-effects here)
        if command.lower() in ["/exit", "exit"]:
            return CommandResult(exit_requested=True, command_type=CommandType.EXIT)

        # Parse first lexical word
        first_word = command.split()[0] if command.split() else ""

        # For 'cd' commands: classify and provide the target path as output, but
        # do NOT perform the actual directory change here.
        if first_word == "cd":
            # Provide the target path (may be empty string if no args)
            target_path = " ".join(command.split()[1:]) if command.split()[1:] else ""
            return CommandResult(output=target_path, command_type=CommandType.CD)

        # Unsupported command classes in non-interactive evaluation (server mode)
        if config.SERVER_MODE and (
            is_interactive_command(command)
            or is_internal_command(command)
            or is_built_in_function(command)
        ):
            logger.debug(
                f"Unsupported command type for non-interactive evaluation: {command}"
            )
            return CommandResult(
                error="Interactive / built-in / internal commands are not supported via non-interactive evaluation.",
                command_type=CommandType.UNSUPPORTED,
            )

        if is_non_interactive_command(command):
            return CommandResult(command_type=CommandType.NON_INTERACTIVE)
        elif is_interactive_command(command):
            return CommandResult(command_type=CommandType.INTERACTIVE)
        elif is_internal_command(command):
            return CommandResult(command_type=CommandType.INTERNAL)
        elif is_built_in_function(command):
            return CommandResult(command_type=CommandType.BUILT_IN)

        # Default: treat as LLM query (classification only; do not execute query())
        logger.debug("Classified as LLM query for command: {}".format(command))
        return CommandResult(command_type=CommandType.LLM)

    except Exception as exc:
        logger.error("Error while evaluating command.", exc_info=True)
        return CommandResult(error=str(exc), command_type=CommandType.ERROR)


def execute_command(command_result: CommandResult, original_command: str, history_file: str) -> CommandResult:
    """
    Perform side-effects for a command previously classified by evaluate_command.

    Parameters:
    - command_result: the result returned by evaluate_command (may be updated)
    - original_command: the command string as provided to the REPL (already macro-expanded
      or raw depending on suppression). This string will be used for query execution
      and contextual updates.
    - history_file: path to the history file; kept for API compatibility in case
      further side-effects need it (not used currently).

    Returns:
    - The possibly-updated CommandResult with output filled for LLM/CD commands and
      exit_requested set if applicable.
    """
    try:
        # No-op for empty commands
        if command_result.command_type == CommandType.EMPTY:
            return command_result

        # Handle explicit exit requests: perform legacy side-effects via handle_exit_command
        if command_result.command_type == CommandType.EXIT or command_result.exit_requested:
            # Use the legacy handler to perform signal/print side-effects
            handle_exit_command(original_command, history_file)
            command_result.exit_requested = True
            return command_result

        # Handle CD: perform the actual directory change and notify the LLM
        if command_result.command_type == CommandType.CD:
            # Determine the target path: prefer the output provided by evaluation,
            # otherwise parse from the original_command
            target_path = command_result.output if command_result.output is not None else (
                " ".join(original_command.split()[1:]) if original_command.split()[1:] else ""
            )
            cwd = handle_cd_command(target_path)
            logger.debug("Changed directory to: {}".format(cwd))
            # Enqueue a prefix for the next LLM interaction to reflect directory changes
            cd_failure_prefixes = (
                "Directory not found:",
                "Not a directory:",
                "Permission denied:",
            )
            if not any(str(cwd).startswith(prefix) for prefix in cd_failure_prefixes):
                try:
                    config.enqueue_next_llm_prefix(f"Be aware I have changed directory to {cwd}")
                except Exception:
                    logger.exception("Failed to enqueue LLM prefix about directory change.")
            command_result.output = cwd
            if command_result.output is not None:
                print(command_result.output)
            return command_result

        if command_result.command_type == CommandType.NON_INTERACTIVE:
            execute_non_interactive_command(original_command)
        elif command_result.command_type == CommandType.INTERACTIVE:
            execute_interactive_command(original_command)
            return command_result
        elif command_result.command_type == CommandType.INTERNAL:
            execute_internal_command(original_command, display_query_result)
            return command_result
        elif command_result.command_type == CommandType.BUILT_IN:
            execute_built_in_function(original_command)
            return command_result

        # Unsupported commands: print error message but do not attempt execution
        if command_result.command_type == CommandType.UNSUPPORTED:
            if command_result.error:
                print(f"{yellow}{command_result.error}{reset}")
            return command_result

        # If evaluation resulted in an error classification, display it
        if command_result.command_type == CommandType.ERROR:
            if command_result.error:
                print(f"{yellow}{command_result.error}{reset}")
            return command_result

        # Handle LLM queries: execute the query(), and only perform follow-up side-effects
        # if the result is a non-empty string. When cancellations or control-flow outcomes
        # are returned (e.g., a ConversationResult enum or other non-string types), we skip
        # send_artifact, display, and context preparation to avoid errors.
        if command_result.command_type == CommandType.LLM:
            try:
                # Execute the LLM query
                from monitor.core.query_service import query
                query_result = query(original_command)
                command_result.output = query_result

                # Only proceed with side-effects if we received a non-empty string.
                # Non-string results may indicate cancellation or control signals.
                if isinstance(query_result, str) and query_result.strip():
                    # Send artifact (side-effect)
                    try:
                        send_artifact(query_result)
                    except Exception:
                        logger.exception("Failed to send artifact for query result.")

                    # Display result and update conversation history count
                    try:
                        display_query_result(
                            query_result,
                            update_history_count=lambda: setattr(
                                monitor.core.conversation,
                                "TOTAL_CONVERSATION_HISTORY_COUNT",
                                monitor.core.conversation.TOTAL_CONVERSATION_HISTORY_COUNT + 2,
                            ),
                        )
                    except Exception:
                        logger.exception("Failed to display query result.")

                    # Prepare query context for future interactions
                    try:
                        prepare_query_context(original_command)
                    except Exception:
                        logger.exception("Failed to prepare query context.")
                else:
                    # For non-string or empty outputs, skip side-effects silently to keep Ctrl-C behavior clean.
                    logger.debug("Query returned no displayable text; skipping side-effects without printing.")
                # If the result is not a non-empty string (e.g., cancellation/enum),
                # we intentionally skip the above side-effects and simply return.

            except Exception as exc:
                logger.exception("Error while executing LLM query.")
                command_result.error = str(exc)
                command_result.command_type = CommandType.ERROR
                # Ensure the error is visible to the user
                print(f"{yellow}{command_result.error}{reset}")

            return command_result

        # For any other command types that might be added in future, default to no-op
        return command_result

    except Exception as exc:
        logger.exception("Unexpected error during command execution.")
        return CommandResult(error=str(exc), command_type=CommandType.ERROR)


def process_cd_command(command, first_word):
    """Process change directory command"""

    if first_word == "cd":
        cwd = handle_cd_command(" ".join(command.split()[1:]))
        logger.debug("Changed directory to: {}".format(cwd))
        cd_failure_prefixes = (
            "Directory not found:",
            "Not a directory:",
            "Permission denied:",
        )
        if not any(str(cwd).startswith(prefix) for prefix in cd_failure_prefixes):
            try:
                config.enqueue_next_llm_prefix(f"Be aware I have changed directory to {cwd}")
            except Exception:
                logger.exception("Failed to enqueue LLM prefix about directory change.")
        return True
    return False


def process_command(command, history_file):
    """Process a single REPL command and return the exit flag."""

    if not command.strip():
        return False

    # Save command history
    try:
        readline.write_history_file(history_file)
    except Exception as e:
        logger.error(
            f"Failed to write command history to {history_file}: {e}", exc_info=True
        )

    # Log and expand macros unless explicitly suppressed with '!<'.
    # Remove only the leading '!<' instance following any leading whitespace.
    if command.lstrip().startswith("!<"):
        logger.info("Macro expansion suppressed for input (found !<)")
        # Remove only the first occurrence of the suppression marker after leading whitespace
        leading_ws_len = len(command) - len(command.lstrip())
        leading_ws = command[:leading_ws_len]
        rest = command[leading_ws_len:]
        if rest.startswith("!<"):
            rest = rest.replace("!<", "", 1)
        command = leading_ws + rest
        logger.info(f"[PROCESS COMMAND] - Using raw command after suppression: {command}")
    else:
        logger.info("[PROCESS COMMAND] - Performing macro expansion for input")
        command = recursive_macro_expand(
            command,
            MACRO_VALUES,
            config.MACRO_DELIMITER_OPEN,
            config.MACRO_DELIMITER_CLOSE,
            config.MACRO_DELIMITER_ESCAPE,
        )

    result = evaluate_command(command)
    result = execute_command(result, command, history_file)

    if result.error:
        print(f"{yellow}{result.error}{reset}")

    return result.exit_requested

def handle_exit_command(command, history_file=None):
    """Handle exit commands and return exit flag"""
    if command.lower() in ["/exit", "exit"]:
        if command.lower() == "/exit":
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            print(f"{yellow}\nEOT{reset}\n")
        logger.info("Exiting chat...")
        return True
    return False


def internalize_command(command):
    """Helper for command evaluation and execution (LLM, built-ins, etc)."""
    result = evaluate_command(command)
    result = execute_command(result, command, config.HISTORY_FILE)
    return {
        "output": result.output,
        "error": result.error,
        "command_type": result.command_type.value if isinstance(result.command_type, CommandType) else str(result.command_type),
        "exit_requested": result.exit_requested,
    }
