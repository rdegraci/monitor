import logging
import signal
import json
import shlex
import os

from monitor import config
from monitor.lib.macros import MACRO_VALUES

try:
    from termcolor import colored
except ImportError:
    # Fallback in case termcolor is not installed
    def colored(text, color):
        return text

from monitor.lib.command_utils import handle_error, run_subprocess

from monitor.lib.macro_utils import recursive_macro_expand

from monitor.core.query_service import query

logger = logging.getLogger(__name__)

ALL_TERMINAL_COMMANDS = []
NON_INTERACTIVE_COMMANDS = []
INTERACTIVE_COMMANDS = []

def load_terminal_commands(interactive_commands_path, non_interactive_commands_path, ):
    global ALL_TERMINAL_COMMANDS
    _load_private_internal_commands()
    _load_non_interactive_commands(non_interactive_commands_path)
    _load_interactive_commands(interactive_commands_path)
    ALL_TERMINAL_COMMANDS = PRIVATE_COMMANDS + INTERNAL_COMMANDS + INTERACTIVE_COMMANDS + NON_INTERACTIVE_COMMANDS

NON_INTERACTIVE_COMMANDS = []
def _load_non_interactive_commands(non_interactive_commands_path):
    global NON_INTERACTIVE_COMMANDS
    NON_INTERACTIVE_COMMANDS = []
    if non_interactive_commands_path is None:
        # No path provided; explicitly ensure the global is an empty list and return early.
        NON_INTERACTIVE_COMMANDS = []
        return
    try:
        with open(non_interactive_commands_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not all(isinstance(cmd, dict) and "command" in cmd for cmd in data):
            logger.error(f"Non-interactive-commands file {non_interactive_commands_path} must be a list of dicts with 'command' fields. Falling back to empty list.")
            print(f"[WARN] Invalid Non-interactive-commands format at {non_interactive_commands_path}; falling back to empty list.")
            NON_INTERACTIVE_COMMANDS = []
            return
        NON_INTERACTIVE_COMMANDS = data
        return
    except Exception as e:
        logger.error(f"Could not load non-interactive-commands from {non_interactive_commands_path}: {e}")
        print(f"[WARN] Could not load non-interactive-commands from {non_interactive_commands_path}: {e} - falling back to empty list.")
        NON_INTERACTIVE_COMMANDS = []
        return

def _load_interactive_commands(interactive_commands_path):
    global INTERACTIVE_COMMANDS
    if interactive_commands_path is None:
        # No path provided; ensure the global is an empty list and return early.
        INTERACTIVE_COMMANDS = []
        return
    try:
        INTERACTIVE_COMMANDS = []
        with open(interactive_commands_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not all(isinstance(cmd, dict) and "command" in cmd for cmd in data):
            logger.error(f"Interactive commands file {interactive_commands_path} must be a list of dicts with 'command' fields. Falling back to empty list.")
            print(f"[WARN] Invalid interactive commands file format at {interactive_commands_path}; falling back to empty list.")
            INTERACTIVE_COMMANDS = []
            return
        INTERACTIVE_COMMANDS=data
        return
    except Exception as e:
        logger.error(f"Could not load interactive commands from {interactive_commands_path}: {e}")
        print(f"[WARN] Could not load interactive commands from {interactive_commands_path}: {e} - falling back to empty list.")
        INTERACTIVE_COMMANDS = []
        return

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
                if ! cat "$full_path" 2>/dev/null; then
                    echo "Error: File not found or inaccessible: $full_path" >&2
                    return 1
                fi
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

def parse_command(command: str) -> tuple[str, list[str], str]:
    """Parse a command string into its first word and remaining tokens.

    This helper attempts to safely parse the provided command using shlex.split
    (POSIX mode). If shlex.split raises a ValueError (e.g., due to malformed
    quoting), the function falls back to a simple whitespace split.

    Args:
        command: The command string to parse.

    Returns:
        A tuple (first_word, rest_tokens, rest_joined) where:
        - first_word is the first token of the parsed command (or an empty string).
        - rest_tokens is a list of the remaining tokens.
        - rest_joined is a string of the remaining tokens joined with proper quoting
          using shlex.join when possible, otherwise a simple space-joined string.
    """
    try:
        tokens = shlex.split(command, posix=True)
        first_word = tokens[0] if tokens else ''
        rest_tokens = tokens[1:] if len(tokens) > 1 else []
        rest_joined = shlex.join(rest_tokens) if rest_tokens else ''
    except ValueError:
        # Fallback: naive split on whitespace if shlex fails
        tokens = command.split()
        first_word = tokens[0] if tokens else ''
        rest_tokens = tokens[1:] if len(tokens) > 1 else []
        rest_joined = " ".join(rest_tokens) if rest_tokens else ''
    return first_word, rest_tokens, rest_joined

def contains_unquoted_shell_metacharacters(remainder: str) -> bool:
    """Return True if the provided remainder string contains unquoted/unescaped
    shell metacharacters that should be preserved when executing via the shell.

    This function scans the string while tracking single- and double-quote contexts
    and backslash escapes. Characters considered shell metacharacters include:
      - Pipe, ampersand, semicolon, redirection, backtick, dollar, parentheses,
        braces, brackets: | & ; < > ` $ ( ) { } [ ]
      - Wildcard/globbing characters: * ? [
    Behavior:
      - Characters inside single quotes are considered quoted and ignored.
      - Inside double quotes, $ and ` are considered active metacharacters (and
        therefore treated as unquoted for the purpose of this check), while other
        metacharacters are treated as quoted.
      - A backslash escapes the next character when not inside single quotes.
    """
    if not remainder:
        return False

    always_metachars = set('|&;<>`$(){}[]')
    wildcard_metachars = set('*?[')

    in_single = False
    in_double = False
    i = 0
    length = len(remainder)

    while i < length:
        ch = remainder[i]

        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue

        if ch == "\\" and not in_single:
            # Escape next character (if any) when not in single quotes
            i += 2
            continue

        # Check always-metacharacters: treat $ and ` as meta even inside double quotes.
        if ch in always_metachars:
            if not in_single:
                # If inside double quotes, only $ and ` still count as active metacharacters.
                if not in_double or ch in ('$', '`'):
                    logger.debug(f"Detected unquoted metacharacter '{ch}' at position {i} in remainder={remainder!r}")
                    return True

        # Check wildcard metacharacters: only count if not quoted (neither single nor double)
        if ch in wildcard_metachars:
            if not in_single and not in_double:
                logger.debug(f"Detected unquoted wildcard metacharacter '{ch}' at position {i} in remainder={remainder!r}")
                return True

        i += 1

    return False

def is_interactive_command(command: str):
    """
    Determine if the given command matches a public or private interactive command.

    Searches both PRIVATE_COMMANDS and INTERACTIVE_COMMANDS for a matching 'command' key.
    """
    first_word, _, _ = parse_command(command)
    return next((cmd for cmd in (PRIVATE_COMMANDS + INTERACTIVE_COMMANDS) if cmd["command"] == first_word), None)

def is_non_interactive_command(command: str):
    first_word, _, _ = parse_command(command)
    return next((cmd for cmd in NON_INTERACTIVE_COMMANDS if cmd["command"] == first_word), None)

def _python_is_interactive(rest_tokens: list[str]) -> bool:
    """Bare ``python`` drops into the REPL (needs a TTY); ``python script.py``,
    ``python -c ...`` and ``python -m ...`` run a program and are output-style.
    ``-i`` forces the REPL even with a script."""
    if not rest_tokens or "-i" in rest_tokens:
        return True
    if "-c" in rest_tokens or "-m" in rest_tokens:
        return False
    # A non-option token is a script path → running a program, not the REPL.
    return not any(not tok.startswith("-") for tok in rest_tokens)


def command_needs_tty(command: str) -> bool:
    """Return True if the command requires a real interactive terminal (full-screen
    rendering and/or reading from the keyboard/stdin), e.g. vim/ssh/top/psql.

    This is the orthogonal "needs a TTY" signal — distinct from which JSON list a
    command lives in. The interactive list contains both true TTY programs and
    output-style tools (git, cat, head, …); only the former carry
    ``"needs_tty": true``. Absence of the flag (or no matching entry) → False.

    A few commands are argument-dependent — the same name is interactive or
    output-style depending on its args — so a flat JSON flag can't be right for
    both. Those are decided here by inspecting the arguments (and so don't even
    need a JSON entry to be classified correctly):
      - ``python``/``python3``: bare REPL needs a TTY; with a script/-c/-m it doesn't.
      - ``crontab``: ``-e`` edits in $EDITOR (TTY); ``-l``/``-r`` are output-style.
      - ``sh``/``bash``/``zsh``: bare shell is interactive; ``-c '…'`` just runs a command.

    Front-ends use this to decide how to run a command: a TTY program must own the
    terminal (in the --tui front-end that means suspending the full-screen app),
    whereas an output-style command can have its output captured. Returns False
    for anything not found in the command lists (e.g. plain LLM queries).
    """
    first_word, rest_tokens, _ = parse_command(command)
    name = os.path.basename(first_word) if first_word else first_word
    if name in ("python", "python3"):
        return _python_is_interactive(rest_tokens)
    if name == "crontab":
        return "-e" in rest_tokens
    if name in ("sh", "bash", "zsh"):
        return "-c" not in rest_tokens
    match = next(
        (cmd for cmd in (PRIVATE_COMMANDS + INTERACTIVE_COMMANDS + NON_INTERACTIVE_COMMANDS)
         if cmd.get("command") == first_word),
        None,
    )
    return bool(match.get("needs_tty", False)) if match else False

def execute_non_interactive_command(command: str):
    """
    Execute a non-interactive command as defined in NON_INTERACTIVE_COMMANDS.

    - If an 'expansion' is matched for the first word in the command in NON_INTERACTIVE_COMMANDS, 
      the expansion string is executed directly (with additional arguments appended) 
      in a non-interactive subshell.
    - If no expansion is found for the matched command, the command itself is executed
      directly in a non-interactive subshell.

    This function now preserves raw shell operators when the original remainder
    contains unquoted/unescaped shell metacharacters. In that case the original
    remainder substring is appended to preserve operators like pipes, redirections,
    and other shell constructs. Otherwise a safe shlex.join of parsed tokens is used.
    """
    first_word, rest_tokens, rest_joined = parse_command(command)
    # Compute the original raw remainder substring from the original command text
    idx = command.find(first_word)
    remainder_raw = command[idx + len(first_word):].lstrip() if idx != -1 else ""
    logger.debug(f"execute_non_interactive_command: first_word={first_word!r}, remainder_raw={remainder_raw!r}, rest_tokens={rest_tokens}")

    # Using shlex for safe argument joining to handle quotes and escapes.
    matching_command = next(
        (cmd for cmd in NON_INTERACTIVE_COMMANDS if cmd["command"] == first_word), None
    )
    command_to_run = None

    try:
        # Choose whether to use the raw remainder (preserve shell metacharacters) or the safe joined tokens
        if remainder_raw:
            try:
                if contains_unquoted_shell_metacharacters(remainder_raw):
                    chosen_remainder = remainder_raw
                    logger.debug("execute_non_interactive_command: Using raw remainder because it contains unquoted shell metacharacters.")
                else:
                    chosen_remainder = shlex.join(rest_tokens) if rest_tokens else ""
                    logger.debug("execute_non_interactive_command: Using shlex.join of rest_tokens (no unquoted metacharacters detected).")
            except Exception as ex_check:
                logger.debug(f"execute_non_interactive_command: Error checking metacharacters: {ex_check}. Falling back to safe joining.")
                chosen_remainder = shlex.join(rest_tokens) if rest_tokens else ""
        else:
            chosen_remainder = ""

        if matching_command is not None:
            command_to_run = matching_command.get("expansion")
            if command_to_run:
                command_to_run += f" {chosen_remainder}" if chosen_remainder else ""
            else:
                command_to_run = f"{first_word} {chosen_remainder}" if chosen_remainder else first_word
        else:
            command_to_run = f"{first_word} {chosen_remainder}" if chosen_remainder else first_word

        logger.info(f"Executing non-interactive command '{first_word}' without macro expansion.")
        logger.debug(f"Executing non-interactive command in subprocess: {command_to_run}")
        preexec = (lambda: signal.signal(signal.SIGINT, signal.SIG_DFL)) if os.name == 'posix' else None
        exit_code, stdout, stderr, process = run_subprocess(
            command_to_run,
            interactive=False,
            shell=True,
            preexec_fn=preexec,
            text=True,
            fetch_output=False,
        )
    except Exception as ex_outer:
        handle_error(
            f"Failed to handle non-interactive command: '{command}'",
            exception=ex_outer,
            error_type="Error",
            log_level="error",
            display=True,
        )

def execute_interactive_command(command: str):
    """
    Execute an interactive command as defined in PRIVATE_COMMANDS and INTERACTIVE_COMMANDS.

    - If an 'expansion' is matched for the first word in the command in PRIVATE_COMMANDS or INTERACTIVE_COMMANDS, 
      the expansion string is executed directly (with additional arguments appended) 
      in an interactive subshell.
    - If no expansion is found for the matched command, the command itself is executed
      directly in an interactive subshell.

    This function now preserves raw shell operators when the original remainder
    contains unquoted/unescaped shell metacharacters. In that case the original
    remainder substring is appended to preserve operators like pipes, redirections,
    and other shell constructs. Otherwise a safe shlex.join of parsed tokens is used.

    All executions use run_subprocess(). Errors are surfaced to the user via handle_error with display=True.
    """
    first_word, rest_tokens, rest_joined = parse_command(command)
    # Compute the original raw remainder substring from the original command text
    idx = command.find(first_word)
    remainder_raw = command[idx + len(first_word):].lstrip() if idx != -1 else ""
    logger.debug(f"execute_interactive_command: first_word={first_word!r}, remainder_raw={remainder_raw!r}, rest_tokens={rest_tokens}")
    # Using shlex for safe argument joining to handle quotes and escapes.
    matching_command = next(
        (cmd for cmd in (PRIVATE_COMMANDS + INTERACTIVE_COMMANDS) if cmd["command"] == first_word), None
    )
    command_to_run = None

    try:
        # Choose whether to use the raw remainder (preserve shell metacharacters) or the safe joined tokens
        if remainder_raw:
            try:
                if contains_unquoted_shell_metacharacters(remainder_raw):
                    chosen_remainder = remainder_raw
                    logger.debug("execute_interactive_command: Using raw remainder because it contains unquoted shell metacharacters.")
                else:
                    chosen_remainder = shlex.join(rest_tokens) if rest_tokens else ""
                    logger.debug("execute_interactive_command: Using shlex.join of rest_tokens (no unquoted metacharacters detected).")
            except Exception as ex_check:
                logger.debug(f"execute_interactive_command: Error checking metacharacters: {ex_check}. Falling back to safe joining.")
                chosen_remainder = shlex.join(rest_tokens) if rest_tokens else ""
        else:
            chosen_remainder = ""

        try:
            if matching_command is not None:
                command_to_run = matching_command.get("expansion")
                if command_to_run:
                    command_to_run += f" {chosen_remainder}" if chosen_remainder else ""
                else:
                    command_to_run = f"{first_word} {chosen_remainder}" if chosen_remainder else first_word
            else:
                command_to_run = f"{first_word} {chosen_remainder}" if chosen_remainder else first_word

            # Only claim the terminal for commands that actually need a TTY
            # (vim/ssh/top/…). Output-style commands in the interactive list
            # (git, cat, head, …) run non-interactively so a front-end can
            # capture their output (the --tui window) instead of having them
            # write straight to the terminal. In the REPL nothing captures, so
            # they still inherit the terminal exactly as before — no regression.
            needs_tty = bool(command_needs_tty(command))
            logger.info(
                f"Executing interactive-list command '{first_word}' (needs_tty={needs_tty})."
            )
            logger.debug(f"Executing command in subprocess: {command_to_run}")
            preexec = (lambda: signal.signal(signal.SIGINT, signal.SIG_DFL)) if os.name == 'posix' else None
            exit_code, stdout, stderr, process = run_subprocess(
                command_to_run,
                interactive=needs_tty,
                shell=True,
                preexec_fn=preexec,
                text=True,
                fetch_output=False,
            )
        except Exception as ex_inner:
            raise ex_inner
    except Exception as ex_outer:
        handle_error(
            f"Failed to handle interactive command: '{command}'",
            exception=ex_outer,
            error_type="Error",
            log_level="error",
            display=True,
        )

def print_terminal_commands(arg=None):
    """
    Print all public interactive command names as a comma-separated list.
    """
    commands = [item["command"] for item in ALL_TERMINAL_COMMANDS if "command" in item]
    command_string = ", ".join(commands)
    print(command_string)
    print("***")

def is_internal_command(command: str):
    first_word, _, _ = parse_command(command)
    return next((cmd for cmd in INTERNAL_COMMANDS if cmd["command"] == first_word), None)

def internalize_to_llm(command: str, display_query_result_call):
    first_word, rest_tokens, rest_joined = parse_command(command)
    # shlex.join ensures rest_of_command is properly quoted if needed, but split on delimiter assumes >llm is not quoted.
    if not rest_tokens:
        handle_error(
            f"No command string provided after 'llm<'",
            error_type="Error",
            log_level="error",
            display=True,
        )
        return

    shell_code_str = ""
    user_prompt_str = None

    # Primary path: token-based split on a standalone >llm token
    if ">llm" in rest_tokens:
        index = rest_tokens.index(">llm")
        shell_tokens = rest_tokens[:index]
        prompt_tokens = rest_tokens[index + 1 :]
        shell_code_str = shlex.join(shell_tokens) if shell_tokens else ""
        user_prompt_str = " ".join(prompt_tokens) if prompt_tokens else None
    else:
        # Fallback: substring-based split on literal '>llm' from the original command string after the first word
        idx = command.find(first_word)
        remainder = command[idx + len(first_word) :].lstrip() if idx != -1 else command
        if ">llm" in remainder:
            before, after = remainder.split(">llm", 1)
            shell_code_str = before.strip()
            user_prompt_str = after.strip() if after.strip() else None
        else:
            shell_code_str = remainder.strip()
            user_prompt_str = None

    if not shell_code_str.strip():
        handle_error(
            f"No shell code segment provided after 'llm<' in command: '{command}'",
            error_type="Error",
            log_level="error",
            display=True,
        )
        return

    preexec = (lambda: signal.signal(signal.SIGINT, signal.SIG_DFL)) if os.name == 'posix' else None
    exit_code, stdout, stderr, process = run_subprocess(
        shell_code_str,
        interactive=False,
        shell=True,
        preexec_fn=preexec,
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
            if user_prompt_str is not None:
                if '${result}' in user_prompt_str:
                    llm_input = user_prompt_str.replace('${result}', result)
                else:
                    if user_prompt_str:
                        if result:
                            llm_input = user_prompt_str.rstrip() + "\n" + result
                        else:
                            llm_input = user_prompt_str.rstrip()
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
                f"Error in query() after successful execution of llm_eval command: {rest_joined}",
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
    try:
        first_word, _, rest_joined = parse_command(command)
    except Exception:
        # parse_command should not raise, but keep original fallback behavior
        try:
            tokens = shlex.split(command, posix=True)
            first_word = tokens[0] if tokens else ''
            rest_joined = shlex.join(tokens[1:]) if len(tokens) > 1 else ''
        except ValueError:
            parts = command.split()
            first_word = parts[0] if parts else ''
            rest_joined = " ".join(parts[1:]) if len(parts) > 1 else ''

    # Using shlex for safe argument joining to handle quotes and escapes.
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

        command_to_run = f"{expansion} {rest_joined}" if expansion else rest_joined
        preexec = (lambda: signal.signal(signal.SIGINT, signal.SIG_DFL)) if os.name == 'posix' else None

        payload = "source ~/.zshrc"
        if command_to_run and command_to_run.strip():
            payload = f"{payload} && {command_to_run}"
        zsh_args = ["zsh", "-c", payload]

        exit_code, stdout, stderr, process = run_subprocess(
            zsh_args,
            interactive=False,
            shell=False,
            preexec_fn=preexec,
            text=True,
            fetch_output=True,
        )
        output_string = stdout if stdout is not None else ""

        # If the internal command requests that output be internalized to the LLM,
        # we must avoid sending error output to the model. Specifically, if the
        # subprocess exited with a non-zero status and produced stderr, surface
        # that stderr to the user and DO NOT send the output to the LLM.
        # Successful runs (exit_code == 0) retain the existing behavior.
        if matching_internal_command.get("internalize_to_llm"):
            if exit_code is not None and exit_code != 0 and stderr:
                # Surface subprocess stderr to the user and skip sending to LLM.
                handle_error(
                    f"Internal command produced errors (exit_code {exit_code}):",
                    exception=stderr,
                    error_type="Error",
                    log_level="warning",
                    display=True,
                )
            else:
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
