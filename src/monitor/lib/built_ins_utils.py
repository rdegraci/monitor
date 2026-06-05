import code
import logging
import inspect
from typing import Any, Callable, Dict, List, Optional

from monitor.lib.redis_utils import fetch_memory_for_context, get_redis_client, dump_memories

logger = logging.getLogger(__name__)


def print_built_ins(arg: str = "") -> None:
    """
    Print a list of available built-in commands grouped by their group description,
    with aligned descriptions.

    Prepends a brief invocation hint (two lines) so new users see how to actually
    run commands without having to dig through other docs.

    Args:
        arg: Additional arguments passed to the command (currently unused).
    """
    if not built_in_functions:
        print("No built-in commands have been registered.")
        return

    # Two-line preamble: how to invoke + how arguments work. Deliberately
    # short — the value is in being skimmable, not exhaustive. The
    # detailed Usage notes already live in each command's description.
    print(
        "Type a command followed by Enter. Most start with ':' "
        "(e.g. ':help', ':dump_metrics')."
    )
    print(
        "Arguments follow the command name with a space "
        "(e.g. ':dump_metrics /tmp/m.json', ':copy_code 2')."
    )

    # Determine the maximum command length across all built-ins for padding
    longest_command_length: int = max(
        len(item["command"]) for item in built_in_functions if "command" in item
    )

    # Group commands by their 'group_description', defaulting to 'General'
    grouped_commands: Dict[str, List[Dict[str, Any]]] = {}
    for item in built_in_functions:
        group_name: str = item.get("group_description", "General")
        grouped_commands.setdefault(group_name, []).append(item)

    # Print commands grouped by group description
    for group_name in sorted(grouped_commands.keys()):
        print(f"\n=== {group_name} ===")
        for item in grouped_commands[group_name]:
            command: str = item.get("command", "")
            description: str = item.get("description", "")
            padded_command: str = command.ljust(longest_command_length)
            print(f"{padded_command}  - {description}")
    print("***")


def start_python_repl(arg: str = "") -> None:
    """
    Start an interactive Python REPL session.

    Args:
        arg: Additional arguments passed to the command (currently unused).
    """
    local_vars: Dict[str, Any] = globals().copy()
    local_vars.update(locals())
    console = code.InteractiveConsole(locals=local_vars)
    console.interact("Starting Python REPL...")


# List of built-in function descriptors
built_in_functions: List[Dict[str, Any]] = [
    {
        "command": ":repl",
        "description": "Starts an interactive Python REPL session.",
        "function": start_python_repl,
        "group_description": "Utilities",
    },
    {
        "command": ":built_ins",
        "description": "Lists all registered built-in commands.",
        "function": print_built_ins,
        "group_description": "Utilities",
    },
    {
        "command": ":memories",
        "description": "Dumps agent memories from Redis.",
        "function": dump_memories,
        "group_description": "Debugging",
    },
    {
        "command": ":help",
        "description": "Displays all registered built-in commands.",
        "function": print_built_ins,
        "group_description": "Utilities",
    },
    {
        "command": "/help",
        "description": "Displays all registered built-in commands.",
        "function": print_built_ins,
        "group_description": "Utilities",
    },
    {
        "command": "/?",
        "description": "Displays all registered built-in commands.",
        "function": print_built_ins,
        "group_description": "Utilities",
    },
]


def append_function_to_built_ins(
    new_dict: Dict[str, Any], arr: List[Dict[str, Any]] = built_in_functions
) -> None:
    """
    Append a new built-in command definition to the list.

    Args:
        new_dict: A dictionary with keys 'command', 'description', and 'function'.
        arr: The list to which the new command will be appended.

    Raises:
        ValueError: If `new_dict` is not a dictionary or `arr` is not a list.
    """
    if isinstance(arr, list) and isinstance(new_dict, dict):
        arr.append(new_dict)
    else:
        raise ValueError("First argument must be a dictionary.")


def is_built_in_function(command: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Check if the given command corresponds to a registered built-in function.

    Args:
        command: The command string entered by the user.

    Returns:
        The matching built-in command dictionary if found, else None.
    """
    if not isinstance(command, str):
        return None

    command_stripped: str = command.strip()
    if not command_stripped:
        return None

    tokens: List[str] = command_stripped.split()
    if not tokens:
        return None

    first_word: str = tokens[0]
    return next(
        (cmd for cmd in built_in_functions if cmd["command"] == first_word), None
    )


def execute_built_in_function(command: Optional[str]) -> None:
    """
    Execute the built-in function matching the first word of the command string.

    This function performs the following:
    - Validates that the resolved built-in entry has a callable 'function'.
    - Normalizes empty arguments to an empty string.
    - Inspects the callable's signature to decide whether to call it with zero
      arguments or with a single string argument (the remainder of the command).
    - Wraps the invocation in a try/except and logs any exception that occurs.

    Args:
        command: The command string entered by the user.
    """
    if not isinstance(command, str):
        return

    command_stripped: str = command.strip()
    if not command_stripped:
        return

    tokens: List[str] = command_stripped.split()
    if not tokens:
        return

    first_word: str = tokens[0]
    matching_command: Optional[Dict[str, Any]] = next(
        (cmd for cmd in built_in_functions if cmd["command"] == first_word), None
    )
    if not matching_command:
        return

    # Prepare arguments: join remaining tokens; normalize empty input to empty string
    arguments: str = " ".join(tokens[1:])
    arg_to_pass: str = arguments if arguments else ""

    logger.debug(
        "Executing built-in function: %s with arguments: %s", first_word, arguments
    )

    function_to_run = matching_command.get("function")
    if not callable(function_to_run):
        logger.error(
            "Built-in command '%s' does not have a callable 'function' entry.", first_word
        )
        return

    # Decide whether to call with zero args or one arg by inspecting the signature.
    call_with_arg: bool = True
    try:
        sig = inspect.signature(function_to_run)
    except (ValueError, TypeError):
        # If we cannot obtain a signature (e.g., builtins or C extension functions),
        # assume the callable accepts positional arguments and pass the argument.
        call_with_arg = True
    else:
        params = sig.parameters
        if len(params) == 0:
            # No parameters declared; call without arguments.
            call_with_arg = False
        else:
            # If any parameter can accept a positional argument (positional-only,
            # positional-or-keyword, or var positional), prefer calling with one arg.
            accepts_positional = any(
                p.kind
                in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.VAR_POSITIONAL,
                )
                for p in params.values()
            )
            call_with_arg = bool(accepts_positional)

    # Invoke the callable safely and log any exceptions.
    try:
        if call_with_arg:
            function_to_run(arg_to_pass)  # type: ignore[misc]
        else:
            function_to_run()  # type: ignore[misc]
    except Exception:
        logger.exception("Exception occurred while executing built-in function: %s", first_word)
