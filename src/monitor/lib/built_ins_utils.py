import code
import logging
import inspect
from typing import Any, Callable, Dict, List, Optional

from monitor.lib.redis_utils import fetch_memory_for_context, get_redis_client, dump_memories

logger = logging.getLogger(__name__)


def print_built_ins(arg: str = "") -> None:
    """Print unified command help (task-grouped discovery).

    Delegates to :func:`monitor.lib.command_help.help_command` so ``:help``,
    ``:built_ins``, and ``?`` share one surface. ``arg`` is forwarded as a
    search query (command name or category).
    """
    from monitor.lib.command_help import help_command

    help_command(arg)


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
        "command": "repl",
        "description": "Starts an interactive Python REPL session.",
        "function": start_python_repl,
        "group_description": "Utilities",
    },
    {
        "command": "built_ins",
        "description": "Alias for :help — unified command discovery by task.",
        "function": print_built_ins,
        "group_description": "Utilities",
    },
    {
        "command": "memories",
        "description": "Dumps agent memories from Redis.",
        "function": dump_memories,
        "group_description": "Debugging",
    },
    {
        "command": "help",
        "description": "Unified command discovery. Usage: :help, :help <command|category>.",
        "function": print_built_ins,
        "group_description": "Utilities",
    },
    {
        "command": "?",
        "description": "Alias for :help — unified command discovery by task.",
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
        new_dict: A built-in command descriptor dictionary. It typically
            includes `command`, `description`, and `function`, and may also
            include metadata such as `group_description`.
        arr: The list to which the new command will be appended.

    Raises:
        ValueError: If `new_dict` is not a dictionary or `arr` is not a list.
    """
    if isinstance(arr, list) and isinstance(new_dict, dict):
        arr.append(new_dict)
    else:
        raise ValueError("First argument must be a dictionary.")


def canonicalize_built_in_invocation(command: Optional[str]) -> Optional[tuple[str, str]]:
    """Normalize a prefixed built-in invocation to its canonical command name.

    Args:
        command: The raw command string entered by the user.

    Returns:
        A tuple of the canonical command name and raw argument string when the
        input is a prefixed built-in invocation candidate, else None.
    """
    if not isinstance(command, str):
        return None

    command_stripped: str = command.strip()
    if not command_stripped:
        return None

    first_word, _, remainder = command_stripped.partition(" ")
    if first_word in {":", "/"}:
        return None

    prefix: str = first_word[0]
    if prefix not in {":", "/"}:
        return None

    canonical_command: str = first_word[1:]
    if not canonical_command:
        return None

    arguments: str = remainder.lstrip()
    return canonical_command, arguments


def is_built_in_function(command: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Check if the given command corresponds to a registered built-in function.

    Args:
        command: The command string entered by the user.

    Returns:
        The matching built-in command dictionary if found, else None.
    """
    normalized_command = canonicalize_built_in_invocation(command)
    if normalized_command is None:
        return None

    canonical_command, _ = normalized_command
    return next(
        (cmd for cmd in built_in_functions if cmd["command"] == canonical_command), None
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

    normalized_command = canonicalize_built_in_invocation(command)
    if normalized_command is None:
        return

    canonical_command, arguments = normalized_command
    matching_command: Optional[Dict[str, Any]] = next(
        (cmd for cmd in built_in_functions if cmd["command"] == canonical_command), None
    )
    if not matching_command:
        return

    # Prepare arguments: join remaining tokens; normalize empty input to empty string
    arg_to_pass: str = arguments if arguments else ""

    logger.debug(
        "Executing built-in function: %s with arguments: %s", canonical_command, arguments
    )

    function_to_run = matching_command.get("function")
    if not callable(function_to_run):
        logger.error(
            "Built-in command '%s' does not have a callable 'function' entry.", canonical_command
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
        logger.exception("Exception occurred while executing built-in function: %s", canonical_command)
