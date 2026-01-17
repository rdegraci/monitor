import code
import logging
from typing import Any, Callable, Dict, List, Optional

from monitor.lib.redis_utils import fetch_memory_for_context, get_redis_client, dump_memories

logger = logging.getLogger(__name__)


def print_built_ins(arg: str = "") -> None:
    """
    Print a list of available built-in commands grouped by their group description,
    with aligned descriptions.

    Args:
        arg: Additional arguments passed to the command (currently unused).
    """
    if not built_in_functions:
        print("No built-in commands have been registered.")
        return

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

    arguments: str = " ".join(tokens[1:])
    logger.debug("Executing built-in function: %s with arguments: %s", first_word, arguments)
    function_to_run: Callable[..., None] = matching_command.get("function")  # type: ignore
    function_to_run(arguments)
