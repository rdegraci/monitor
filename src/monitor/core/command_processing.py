import readline
import logging
import signal
from monitor import config
import monitor.core.conversation

logger = logging.getLogger(__name__)

from monitor.core.commands import (
    is_interactive_command,
    execute_interactive_command,
    is_internal_command,
    execute_internal_command
)

from monitor.core.conversation import prepare_query_context
from monitor.core.query_service import query
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
    """
    try:
        if not command.strip():
            return CommandResult(command_type=CommandType.EMPTY)

        # Expand macros in the command unless explicitly suppressed with '!<'
        if not command.lstrip().startswith("!<"):
            command = recursive_macro_expand(
                command,
                MACRO_VALUES,
                config.MACRO_DELIMITER_OPEN,
                config.MACRO_DELIMITER_CLOSE,
                config.MACRO_DELIMITER_ESCAPE,
            )
        else:
            command = command.replace("!<", "")

        # Detect exit commands early
        if command.lower() in ["/exit", "exit"]:
            return CommandResult(exit_requested=True, command_type=CommandType.EXIT)

        # Parse first lexical word
        first_word = command.split()[0] if command.split() else ""

        # Handle 'cd' command
        if first_word == "cd":
            cwd = handle_cd_command(" ".join(command.split()[1:]))
            logger.debug("Changed directory to: {}".format(cwd))
            # Informing the LLM of directory changes is a side effect and is
            # intentionally omitted here.
            return CommandResult(output=cwd, command_type=CommandType.CD)

        # For non-interactive evaluation, do not process special command types here.
        # All commands that are not handled as macros, cd, internal, built-in, or exit
        # fall through as CommandType.LLM.

        # Unsupported command classes in non-interactive evaluation
        if (
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

        # Default: treat as LLM query.
        logger.debug("Executing LLM query evaluation for command: {}".format(command))
        command_string = command.replace("!<", "")
        query_result = query(command_string)
        return CommandResult(output=query_result, command_type=CommandType.LLM)

    except Exception as exc:
        logger.error("Error while evaluating command.", exc_info=True)
        return CommandResult(error=str(exc), command_type=CommandType.ERROR)


def process_cd_command(command, first_word):
    """Process change directory command"""

    if first_word == "cd":
        cwd = handle_cd_command(" ".join(command.split()[1:]))
        logger.debug("Changed directory to: {}".format(cwd))
        query(f"Be aware I have changed directory to {cwd}")
        return True
    return False


def process_command(command, history_file):
    """Process a single command in REPL context and return exit flag"""

    if not command.strip():
        return False

    # Save command history
    try:
        readline.write_history_file(history_file)
    except Exception as e:
        logger.error(
            f"Failed to write command history to {history_file}: {e}", exc_info=True
        )

    if not command.lstrip().startswith("!<"):
        command = recursive_macro_expand(
            command,
            MACRO_VALUES,
            config.MACRO_DELIMITER_OPEN,
            config.MACRO_DELIMITER_CLOSE,
            config.MACRO_DELIMITER_ESCAPE,
        )
    else:
        command = command.replace("!<", "")

    # Legacy behavior: exit command handling
    if handle_exit_command(command):
        return True

    # Legacy behavior: determine first word
    first_word = command.split()[0] if command and command.split() else ""

    # Legacy behavior: change directory command handling
    if process_cd_command(command, first_word):
        return False

    # Legacy behavior: interactive, internal, and built-in commands
    if is_interactive_command(command):
        execute_interactive_command(command)
        return False
    elif is_internal_command(command):
        execute_internal_command(command, display_query_result)
        return False
    elif is_built_in_function(command):
        execute_built_in_function(command)
        return False

    # Evaluate the command with the new side-effect-free routine
    result = evaluate_command(command)

    # Handle output and side effects appropriate for the REPL environment
    if result.command_type in (CommandType.MACRO, CommandType.CD) and result.output is not None:
        print(result.output)
    elif result.command_type == CommandType.LLM:
        send_artifact(result.output)
        display_query_result(
            result.output,
            update_history_count=lambda: setattr(
                monitor.core.conversation,
                "TOTAL_CONVERSATION_HISTORY_COUNT",
                monitor.core.conversation.TOTAL_CONVERSATION_HISTORY_COUNT + 2,
            ),
        )
        prepare_query_context(command)

    # Display errors in a distinct color for visibility
    if result.error:
        print(f"{yellow}{result.error}{reset}")

    return result.exit_requested

def handle_exit_command(command):
    """Handle exit commands and return exit flag"""
    if command.lower() in ["/exit", "exit"]:
        if command.lower() == "/exit":
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            print(f"{yellow}\nEOT{reset}\n")
        logger.info("Exiting chat...")
        return True
    return False


def internalize_command(command):
    """Backward-compatible helper delegating to evaluate_command()."""
    return evaluate_command(command).output
