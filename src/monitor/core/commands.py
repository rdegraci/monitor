import logging
import signal
import json

from monitor import config
from monitor.lib.macros import MACRO_VALUES

try:
    from termcolor import colored
except ImportError:
    # Fallback in case termcolor is not installed
    def colored(text, color):
        return text

from monitor.lib.command_utils import get_first_word, handle_error, run_subprocess

from monitor.lib.macro_utils import recursive_macro_expand

from monitor.core.query_service import query

logger = logging.getLogger(__name__)

ALL_TERMINAL_COMMANDS=[]
INTERACTIVE_COMMANDS=[]

def load_terminal_commands(commands_path):
    global ALL_TERMINAL_COMMANDS, INTERACTIVE_COMMANDS
    _load_private_internal_commands()
    try:
        with open(commands_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not all(isinstance(cmd, dict) and "command" in cmd for cmd in data):
            logger.error(f"Public commands file {commands_path} must be a list of dicts with 'command' fields. Falling back to empty list.")
            print(f"[WARN] Invalid public commands file format at {commands_path}; falling back to empty list.")
            ALL_TERMINAL_COMMANDS = []
            INTERACTIVE_COMMANDS = PRIVATE_COMMANDS
            return []
        ALL_TERMINAL_COMMANDS=data
        INTERACTIVE_COMMANDS = PRIVATE_COMMANDS + ALL_TERMINAL_COMMANDS
    except Exception as e:
        logger.error(f"Could not load public interactive commands from {commands_path}: {e}")
        print(f"[WARN] Could not load public interactive commands from {commands_path}: {e} - falling back to empty list.")
        ALL_TERMINAL_COMMANDS = []
        INTERACTIVE_COMMANDS = PRIVATE_COMMANDS
        return []

PRIVATE_COMMANDS = []
INTERNAL_COMMANDS = []

def _load_private_internal_commands():
    global PRIVATE_COMMANDS, INTERNAL_COMMANDS
    # List of private interactive commands each represented as a dictionary with properties "command" and "expansion"
    # The "expansion" field may be:
    #   - an executable file path
    #   - a shell command string
    #   - a shell function definition (run immediately, e.g., 'function _x() {...}; _x')
    PRIVATE_COMMANDS = [
        {
            "command": "git-init",
            "expansion": """
            function _git_init() { 
                git init; 
                git config user.name "Rodney Degracia"; 
                git config user.email "rdegraci@gmail.com"; 
            }; 
            _git_init
            """,
        },
    ]

    # Both commands def< and comment< pull a template from a file, substitute in user arguments, and route 
    # the final text to your application's internal display handler, facilitating the 
    # rapid generation of code or comments according to predefined patterns.
    # The llm< command, by contrast, uses shell code and user prompts rather than substituting from a template file.
    INTERNAL_COMMANDS = [
        {
            "command": "llm<",
            "llm_eval": True,
            "help": """
            Dynamically runs shell code to gather data, then sends it (optionally with a prompt) to the LLM for analysis/generation.

            Syntax: llm< [shell_code] [>llm [user_prompt]]
            - shell_code: Required; runs to capture output (e.g., 'git status' or '$(cat file.py)').
            - >llm (optional): Delimiter to separate shell_code from user_prompt.
            - user_prompt: Instructions for LLM (e.g., 'Analyze for bugs'); uses ${result} placeholder for output.
            - Requires: OpenAI API key (via config/env); configured model (e.g., gpt-4o).
            - Output: LLM response, displayed via internal handler (streamed, colored).

            Examples:
            - llm< \"git status\"
              → LLM analyzes repo status generically (e.g., 'You're on main with unstaged changes').
            - llm< \"$(cat ./src/monitor/core/commands.py)\" >llm \"Explain execute_internal_command and suggest improvements.\"
              → LLM reviews the function (e.g., 'It matches commands, expands macros, routes to display... Add recursion guards.').
            - llm< \"git diff HEAD^\" >llm \"Review changes for bugs. Use ${result} as diff.\"
              → LLM critiques recent commit (e.g., 'Line 380: Potential loop if output is recursive.').

            Notes: Shell errors abort LLM call. Prompts respect token limits (configurable). Great for AI-assisted code review/debugging.
            """
        },
        {
            "command": "directive<",
            "expansion": f"""!< function _directive_cat() {{
                if [[ $# -eq 0 ]]; then
                    echo "Usage: directive< <file_name>"
                    return 1
                fi
                local file_name="$1"
                local parameter1="param1=$2"
                local parameter2="param2=$3"
                local parameter3="param3=$4"
                local parameter4="param4=$5"
                local parameter5="param5=$6"
                local full_path="{config.DIRECTIVES_DIR}/$file_name"
                echo "$parameter1"
                echo "$parameter2"
                echo "$parameter3"
                echo "$parameter4"
                echo "$parameter5"
                echo "Directives are located in '{config.DIRECTIVES_DIR}'"
                cat "$full_path" 2>/dev/null || echo "Error: File not found or inaccessible: $full_path"
            }}; _directive_cat""",
            "internalize_to_llm": True,  # Evaluates the contents as LLM instructions
            "help": f"""
            Executes a directive file located in the {config.DIRECTIVES_DIR}. Allows up to
            five parameters that the directive may use for configuration.

            Syntax: directive< <file_name> <parameter1> <parameter2> <parameter3> <parameter4> <parameter5>
            - file_name: Required single argument (e.g., 'aa1').
            - parameter1: Optional single argument (e.g., 'param1').
            - parameter2: Optional single argument (e.g., 'param2').
            - parameter3: Optional single argument (e.g., 'param3').
            - Output: The output from executing a directive, with the given parameters.

            Examples:
            - directive< create_spec source_file target_file
              → Executes directive create_spec giving two parameters source_file and target_file
            """
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

    All executions use run_subprocess(). Errors are surfaced to the user via handle_error with display=True.
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

        logger.info(f"Executing interactive command '{first_word}' without macro expansion.")
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

def print_interactive_commands(arg=None):
    """
    Print all public interactive command names as a comma-separated list.
    """
    commands = [item["command"] for item in ALL_TERMINAL_COMMANDS if "command" in item]
    command_string = ", ".join(commands)
    print(command_string)
    print("***")

def is_internal_command(command: str):
    first_word = get_first_word(command)
    return next((cmd for cmd in INTERNAL_COMMANDS if cmd["command"] == first_word), None)

def internalize_to_llm(command: str, display_query_result_call):
    first_word = get_first_word(command)
    rest_of_command = command[len(first_word):].lstrip()
    if not rest_of_command:
        handle_error(
            f"No command string provided after 'llm<'",
            error_type="Error",
            log_level="error",
            display=True,
        )
        return

    shell_code = None
    user_prompt = None
    if '>llm' in rest_of_command:
        try:
            shell_code, user_prompt = rest_of_command.split('>llm', 1)
            shell_code = shell_code.strip()
            user_prompt = user_prompt.strip()
        except Exception as parse_ex:
            handle_error(
                f"Error parsing llm< ... >llm syntax in command: '{command}'",
                exception=parse_ex,
                error_type="Parse Error",
                log_level="error",
                display=True,
            )
            return
    else:
        shell_code = rest_of_command
        user_prompt = None

    if not shell_code:
        handle_error(
            f"No shell code segment provided after 'llm<' in command: '{command}'",
            error_type="Error",
            log_level="error",
            display=True,
        )
        return

    exit_code, stdout, stderr, process = run_subprocess(
        shell_code,
        interactive=False,
        shell=True,
        preexec_fn=None,
        text=True,
        fetch_output=True,
    )
    result = stdout if stdout is not None else ''
    if stdout is None:
        logger.warning("run_subprocess() for llm< command returned None for stdout; using empty string.")

    if result is not None:
        result = result.strip()

    if exit_code == 0:
        try:
            llm_input = None
            if user_prompt is not None:
                if '${result}' in user_prompt:
                    llm_input = user_prompt.replace('${result}', result)
                else:
                    if user_prompt:
                        if result:
                            llm_input = user_prompt.rstrip() + "\n" + result
                        else:
                            llm_input = user_prompt.rstrip()
                    else:
                        llm_input = result
            else:
                llm_input = result
            if llm_input is None:
                llm_input = ""
            llm_input = llm_input.strip()
            if not llm_input:
                logger.warning("Empty input for llm< command after assembling prompt and result; skipping LLM query.")
                handle_error(
                    "Warning: Nothing to send to LLM (empty input after processing).",
                    error_type="Warning",
                    log_level="warning",
                    display=True,
                )
                return
            query_result = query(llm_input)
            display_query_result_call(query_result)
        except Exception as ex:
            handle_error(
                f"Error in query() after successful execution of llm_eval command: {rest_of_command}",
                exception=ex,
                error_type="Error",
                log_level="error",
                display=True,
            )
        return
    else:
        handle_error(
            f"llm_eval command failed (exit_code {exit_code})",
            exception=stderr,
            error_type="Error",
            log_level="error",
            display=True,
        )
        return

def execute_internal_command(command: str, display_query_result):
    first_word = get_first_word(command)
    matching_internal_command = None

    try:
        matching_internal_command = next(
            (cmd for cmd in INTERNAL_COMMANDS if cmd["command"] == first_word), None
        )
        if not matching_internal_command:
            handle_error(
                f"Unknown internal command: {first_word}",
                error_type="Error",
                log_level="error",
                display=True,
            )
            return

        if first_word == "llm<" and matching_internal_command.get("llm_eval"):
            internalize_to_llm(command, display_query_result)
            return

        expansion = matching_internal_command.get("expansion")
        try:
            if expansion is None:
                expansion = ""
            else:
                if expansion.startswith("!<"):
                    logger.info(f"Macro expansion suppressed for internal command '{first_word}'; using raw expansion: {expansion}")
                    expansion = expansion[2:]
                else:
                    logger.info(f"Macro expansion will be performed for internal command '{first_word}': {expansion}")
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
                        expansion = ""
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

        if matching_internal_command.get("internalize_to_llm"):
            try:
                llm_result = query(output_string if output_string is not None else "")
                display_query_result(llm_result)
            except Exception as ex:
                handle_error(
                    "Error sending command output to LLM",
                    exception=ex,
                    error_type="Error",
                    log_level="error",
                    display=True,
                )
        elif matching_internal_command.get("internalize"):
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
