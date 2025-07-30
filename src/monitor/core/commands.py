import logging
import signal
import json
import os

from monitor.lib.macros import MACRO_VALUES

from pygments import highlight
from pygments.lexers import BashLexer
from pygments.formatters import TerminalFormatter, TerminalTrueColorFormatter as TTerminalFormatter

try:
    from termcolor import colored
except ImportError:
    # Fallback in case termcolor is not installed
    def colored(text, color):
        return text

from monitor.lib.command_utils import get_first_word, handle_error, run_subprocess
from monitor.lib.git import (
    perform_git_status,
    perform_git_diff,
    perform_git_log,
    perform_git_stash,
)

from monitor import config

logger = logging.getLogger(__name__)

PUBLIC_INTERACTIVE_COMMANDS=None
INTERACTIVE_COMMANDS=None

def load_public_interactive_commands(commands_path):
    global PUBLIC_INTERACTIVE_COMMANDS, INTERACTIVE_COMMANDS
    try:
        with open(commands_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not all(isinstance(cmd, dict) and "command" in cmd for cmd in data):
            logger.error(f"Public commands file {commands_path} must be a list of dicts with 'command' fields. Falling back to empty list.")
            print(f"[WARN] Invalid public commands file format at {commands_path}; falling back to empty list.")
            return []
        PUBLIC_INTERACTIVE_COMMANDS=data
        INTERACTIVE_COMMANDS = private_interactive_commands + PUBLIC_INTERACTIVE_COMMANDS
    except Exception as e:
        logger.error(f"Could not load public interactive commands from {commands_path}: {e}")
        print(f"[WARN] Could not load public interactive commands from {commands_path}: {e} - falling back to empty list.")
        return []

# List of interactive commands each represented as a dictionary with properties "command" and "expansion"
# The "expansion" field may be:
#   - an executable file path
#   - a shell command string
#   - a shell function definition (run immediately, e.g., 'function _x() {...}; _x')
private_interactive_commands = [
    {
        "command": "review-script",
        "expansion": "/Users/rdegraci/Hack/utils/review.sh",
    },
    {
        "command": "git-init",
        "expansion": 'function _git_init() { git init; git config user.name "Rodney Degracia"; git config user.email "rdegraci@gmail.com"; }; _git_init',
    },
    {
        "command": "subl-monitor",
        "expansion": "subl /Users/rdegraci/Hack/monitor/app.py",
    },
    {
        "command": "subl-monitor-dir",
        "expansion": "subl /Users/rdegraci/Hack/monitor",
    },
]



internal_commands = [
    {
        "command": "def<",
        "expansion": "!< function _sub_params() { local content=$(cat ~/.config/monitor/function_definition); for i in {1..$#}; do content=$(echo \"$content\" | sed \"s/\\${i}/$(P)i/g\"); done; echo \"$content\"; }; _sub_params",
        "internalize": True,
    },
    {
        "command": "comment<",
        "expansion": "!< function _func_comment() { local content=$(cat ~/.config/monitor/function_comment); for i in {1..$#}; do content=$(echo \"$content\" | sed \"s/\\${i}/$(P)i/g\"); done; echo \"$content\"; }; _func_comment",
        "internalize": True,
    },
]


def is_interactive_command(command: str):
    first_word = get_first_word(command)
    return next((cmd for cmd in INTERACTIVE_COMMANDS if cmd["command"] == first_word), None)



def execute_interactive_command(command: str):
    """
    Execute an interactive command as defined in INTERACTIVE_COMMANDS.

    - If an 'expansion' is matched for the first word in the command in INTERACTIVE_COMMANDS, 
      the expansion string is executed directly (with additional arguments appended) 
      in an interactive subshell.
    - If no expansion is found for the matched command, the command itself is executed
      directly in an interactive subshell.

    All executions use run_subprocess(). Error reporting is always shown to the user
    if 'display' is set to True, including exception details.
    """
    first_word = get_first_word(command)
    matching_command = next(
        (cmd for cmd in INTERACTIVE_COMMANDS if cmd["command"] == first_word), None
    )
    command_to_run = None

    try:
        if matching_command is not None:
            command_to_run = matching_command.get("expansion")
            if command_to_run:
                command_to_run += f" {' '.join(command.split()[1:])}"
            else:
                command_to_run = (
                    f"{first_word} {' '.join(command.split()[1:])}"
                )
        else:
            command_to_run = (
                f"{first_word} {' '.join(command.split()[1:])}"
            )

        logger.debug(f"Executing command in subprocess: {command_to_run}")
        exit_code, stdout, stderr, process = run_subprocess(
            command_to_run,
            interactive=True,
            shell=True,
            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
            text=True,
            fetch_output=False,
        )
        # Wait for process to finish for interactivity
        if process is not None:
            try:
                process.wait()
                try:
                    out, err = process.communicate()
                except Exception as cex:
                    handle_error(
                        f"Failed to retrieve command output for '{command}'",
                        exception=cex,
                        error_type="Error",
                        log_level="error",
                    )
                    out, err = None, None

                if out:
                    print(out, end="")
                if err:
                    handle_error(
                        f"Command error output",
                        exception=err,
                        error_type="Command Error",
                        log_level="error",
                        display=True,
                    )
            except Exception as ex:
                handle_error(
                    "An unexpected error occurred during command execution",
                    exception=ex,
                    error_type="Error",
                    log_level="error",
                    display=True,
                )
    except Exception as ex_outer:
        handle_error(
            f"Failed to handle interactive command: '{command}'",
            exception=ex_outer,
            error_type="Error",
            log_level="error",
            display=True,
        )


def print_interactive_commands(arg):
    """
    Print all public interactive command names as a comma-separated list.
    """
    commands = [item["command"] for item in PUBLIC_INTERACTIVE_COMMANDS if "command" in item]
    command_string = ", ".join(commands)
    print(command_string)
    print("***")


def is_internal_command(command: str):
    first_word = get_first_word(command)
    return next((cmd for cmd in internal_commands if cmd["command"] == first_word), None)


def execute_internal_command(command: str, display_query_result):
    """
    Executes a command from internal_commands. If internalize=True, output is passed to
    display_query_result instead of printed.

    All errors are displayed if display is set, and exception details are always shown.
    """
    first_word = get_first_word(command)
    matching_internal_command = None

    try:
        matching_internal_command = next(
            (cmd for cmd in internal_commands if cmd["command"] == first_word), None
        )
        if not matching_internal_command:
            handle_error(
                f"Unknown internal command: {first_word}",
                error_type="Error",
                log_level="error",
                display=True,
            )
            return

        expansion = matching_internal_command.get("expansion")
        try:
            if not expansion.startswith("!<"):
                try:
                    expansion = recursive_macro_expand(expansion, MACRO_VALUES, config.MACRO_DELIMITER_OPEN, config.MACRO_DELIMITER_CLOSE, config.MACRO_DELIMITER_ESCAPE)
                except Exception as ex_macro:
                    handle_error(
                        f"Macro expansion failed for command '{command}'",
                        exception=ex_macro,
                        error_type="Error",
                        log_level="error",
                        display=True,
                    )
            else:
                expansion = expansion[2:]
        except Exception as ex_exp:
            handle_error(
                f"Expansion parsing failed for '{command}'",
                exception=ex_exp,
                error_type="Error",
                log_level="error",
                display=True,
            )
            expansion = ""

        command_to_run = (
            f"{expansion} {' '.join(command.split()[1:])}" if expansion else " ".join(command.split()[1:])
        )
        exit_code, stdout, stderr, process = run_subprocess(
            f"zsh -c 'source ~/.zshrc && {command_to_run}'",
            interactive=False,
            shell=True,
            preexec_fn=None,
            text=True,
            fetch_output=True,
        )
        output_string = stdout if stdout is not None else ""

        if matching_internal_command.get("internalize"):
            display_query_result(output_string)
        else:
            print(output_string, end="")

        if exit_code is not None and exit_code != 0 and stderr:
            for line in stderr.splitlines(keepends=True):
                logger.warning("Subprocess stderr: {}".format(line))
    except Exception as final_ex:
        handle_error(
            f"Unexpected error in internal command execution: '{command}'",
            exception=final_ex,
            error_type="Fatal Error",
            log_level="error",
            display=True,
        )
