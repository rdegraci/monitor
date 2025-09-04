from monitor import config 
import logging

from typing import Any, Callable, Dict, List
import inspect

from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE

from monitor.lib.macros import print_macros, configure_macros, MACRO_VALUES
from monitor.core.conversation import adjust_history_size, conversation_history_command
from monitor.core.commands import print_interactive_commands
from monitor.core.commit import make_commit_command
from monitor.core.internalize_commands import rip_grep_command
from monitor.core.modes import design_mode_command, dev_mode_command

from monitor.lib.built_ins_utils import append_function_to_built_ins
from monitor.lib.commit_analysis import next_steps
from monitor.lib.built_in_commands import clean_missing_values_command, normalize_data_command
from monitor.lib.built_in_commands import (
    linkedin_summary_command,
    open_preferences_command,
    print_tools_command,
    reset_conversation_history_command,
    twitch_summary_command,
    edit_macros_command,
    reload_macros_command,
    llm_command,
    reasoning_command,
    trim_history_command,
    compact_history_command,
)
from monitor.lib.tool_loading import (
    add_db_tools,
    add_modelling_tools,
    remove_db_tools,
    remove_modelling_tools,
)
from monitor.lib.terminal_commands import run_command_in_screen
from monitor.lib.semantic_store import semantic_store_command
from monitor.lib.rag import query_using_rag, send_directory_to_indexing_service
from monitor.lib.ripgrep_search import grep_command
from monitor.lib.protocol_engine import stream_code
from monitor.lib.display_output import print_colored_error

from monitor.lib.external_services import (
    joke_for_twitch,
    send_file_to_indexing_service,
    send_twitch_message_command,
    send_twitter_message,
)

from monitor.lib.colors import COLOR_WARNING_FUNCS

logger = logging.getLogger(__name__)


def _make_callable(func: Callable[..., Any]) -> Callable[[Any], Any]:
    """Create a single-argument-compatible callable wrapper for func.

    This adapter uses inspect.signature to inspect the underlying function's
    parameters and only adapts functions that accept zero or one positional
    argument (or accept a varargs parameter). If the function requires more
    than one positional parameter, the returned wrapper will raise a
    TypeError instructing the caller to register an explicit adapter.

    Behavior:
        - If the function accepts no positional parameters, the wrapper will
          call func() regardless of whether an argument is provided.
        - If the function accepts exactly one positional parameter, the wrapper
          will attempt to call func(arg) when an argument is provided and
          fall back to func() when called with no argument (preserving prior
          lenient behavior).
        - If the function has a *args parameter, the wrapper will attempt to
          call func(arg) or func() as above.
        - If the function requires more than one positional parameter, the
          wrapper will raise a TypeError explaining that an explicit adapter
          (e.g., a lambda) should be registered.

    Args:
        func: The original function to adapt.

    Returns:
        A callable that accepts one optional argument and either invokes `func`
        appropriately or raises a clear TypeError when adaptation is unsafe.

    Note:
        This is intentionally conservative: functions that require more than
        one positional argument must be wrapped by the caller with an explicit
        adapter so their parameter needs are made explicit at registration time.
    """
    sig = inspect.signature(func)
    params = list(sig.parameters.values())

    # Identify positional parameters and varargs
    positional_params = [
        p for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    has_var_positional = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)

    # If the function accepts varargs, treat it as acceptable.
    if has_var_positional:
        def _wrapper(arg: Any = None) -> Any:
            try:
                if arg is None:
                    return func()
                return func(arg)
            except TypeError:
                # Fallback for callables that still error when given the argument
                return func()
        return _wrapper

    # If the function accepts no positional parameters
    if len(positional_params) == 0:
        def _wrapper(arg: Any = None) -> Any:
            return func()
        return _wrapper

    # If the function accepts exactly one positional parameter
    if len(positional_params) == 1:
        def _wrapper(arg: Any = None) -> Any:
            try:
                if arg is None:
                    return func()
                return func(arg)
            except TypeError:
                # Preserve forgiving behavior in case the underlying function
                # chooses to raise when called with an argument.
                return func()
        return _wrapper

    # Function requires more than one positional parameter; require explicit adapter.
    def _wrapper(arg: Any = None) -> Any:
        raise TypeError(
            f"Function '{getattr(func, '__name__', str(func))}' requires more than one positional "
            "argument. Register an explicit adapter (e.g., a lambda) when adding to built-ins."
        )

    return _wrapper


def _safe_register(mapping: Dict[str, Callable[..., Any]]) -> None:
    """
    Register a command-function mapping with the built-ins registry safely.

    The helper logs successes and prints errors without interrupting
    the registration flow.

    Args:
        mapping: A dictionary containing:
            - "command": The command string to be registered.
            - "function": The callable to execute for the command.
            - "description": A human-readable description of the command.
            - "group_description": The descriptive label for the command group.
    """
    try:
        append_function_to_built_ins(mapping)
        logger.debug(
            "Registered built-in command '%s' - %s",
            mapping.get("command"),
            mapping.get("description", "No description provided."),
        )
    except Exception as exc:  # noqa: BLE001
        print_colored_error(f"Failed to register '{mapping.get('command')}': {exc}")


def next_steps_command(arg: Any = None) -> None:
    """Adapter for ':next_steps' that parses branch arguments and delegates.

    Accepts a single optional string containing one or two whitespace-separated tokens:
    the feature branch name and optionally the main branch name. When only one token
    is provided, defaults the main branch to "master". When both are provided,
    calls next_steps(branch, main_branch).

    Args:
      arg: Optional string of the form "<branch>" or "<branch> <main_branch>".

    Returns:
      None. Prints a usage message on invalid input.

    Usage:
      :next_steps my-feature
      :next_steps my-feature main
    """
    # Help handling
    if arg is not None:
        try:
            help_text = str(arg).strip()
        except Exception:
            help_text = ""
        if help_text.lower() in ("help", "-h", "--help"):
            print(
                "Usage: :next_steps <branch> [<main_branch>]\n"
                'Description: Suggest next steps based on commit analysis. If <main_branch> is omitted, "master" is used.\n'
                "Examples:\n"
                "  :next_steps my-feature\n"
                "  :next_steps my-feature main\n"
                "  :next_steps bugfix/issue-123 develop"
            )
            return
    if arg is None:
        print_colored_error("Usage: :next_steps <branch> [<main_branch>]")
        return
    try:
        text = str(arg).strip()
    except Exception:
        print_colored_error("Usage: :next_steps <branch> [<main_branch>]")
        return
    if not text:
        print_colored_error(
            "Usage: :next_steps <branch> [<main_branch>]\n"
            'Description: Suggest next steps based on commit analysis. If <main_branch> is omitted, "master" is used.\n'
            "Examples:\n"
            "  :next_steps my-feature\n"
            "  :next_steps my-feature main\n"
            "  :next_steps bugfix/issue-123 develop"
        )
        return
    parts = text.split()
    if len(parts) == 1:
        branch = parts[0]
        main_branch = "master"
    elif len(parts) == 2:
        branch, main_branch = parts
    else:
        print_colored_error(
            "Usage: :next_steps <branch> [<main_branch>]\n"
            'Description: Suggest next steps based on commit analysis. If <main_branch> is omitted, "master" is used.\n'
            "Examples:\n"
            "  :next_steps my-feature\n"
            "  :next_steps my-feature main\n"
            "  :next_steps bugfix/issue-123 develop"
        )
        return
    next_steps(branch, main_branch)


def configure_built_ins() -> None:
    """
    Register all built-in commands required by the application.

    The function is idempotent and can be called multiple times safely.
    """
    command_groups: List[Dict[str, Any]] = [
        {
            "group_description": "General utility commands",
            "commands": [
                {
                    "command": "commands",
                    "function": _make_callable(print_interactive_commands),
                    "description": "Print the list of interactive commands.",
                },
                {
                    "command": "history",
                    "function": lambda arg=None: conversation_history_command(arg, 10),
                    "description": "Show conversation history.",
                },
                {
                    "command": ":history_size",
                    "function": lambda arg=None: adjust_history_size(
                        int(arg) if arg and str(arg).strip() else None,
                        config.CONVERSATION_HISTORY,
                        config.CONVERSATION_MAX_SIZE,
                        print,
                        COLOR_WARNING_FUNCS,
                        logger,
                        config
                    ),
                    "description": "Adjust max conversation history size.",
                },
                {
                    "command": ":reset_history",
                    "function": _make_callable(reset_conversation_history_command),
                    "description": "Reset the conversation history.",
                },
                {
                    "command": ":trim_history",
                    "function": _make_callable(trim_history_command),
                    "description": "Trim last N items from conversation history.",
                },
                {
                    "command": ":compact_history",
                    "function": lambda arg=None: (
                        compact_history_command(
                            arg,
                            config,
                            print,
                            COLOR_WARNING_FUNCS,
                            logger
                        )
                    ),
                    "description": "Trim history and set the max to N messages (usage: :compact N)."
                },
                {
                    "command": ":llm",
                    "function": _make_callable(llm_command),
                    "description": "Change the active LLM model at runtime. Usage: :llm <model> or :llm help for available models.",
                },
                {
                    "command": ":reasoning",
                    "function": _make_callable(reasoning_command),
                    "description": "Change reasoning effort (minimal/low/medium/high). Usage: :reasoning <level> or :reasoning help.",
                },
                {
                    "command": "macros",
                    "function": _make_callable(print_macros),
                    "description": "Print available macros.",
                },
                {
                    "command": ":edit_macros",
                    "function": _make_callable(edit_macros_command),
                    "description": "Edit global macros file (persistent across sessions). Uses your $EDITOR.",
                },
                {
                    "command": ":reload_macros",
                    "function": _make_callable(reload_macros_command),
                    "description": "Reload global macros from file and summarize changes.",
                },
                {
                    "command": "tools",
                    "function": _make_callable(print_tools_command),
                    "description": "Print currently loaded tools.",
                },
                {
                    "command": ":preferences",
                    "function": _make_callable(open_preferences_command),
                    "description": "Open user preferences for editing.",
                },
                {
                    "command": ":next_steps",
                    "function": _make_callable(next_steps_command),
                    "description": "Suggest next steps based on commit analysis.",
                },
            ],
        },
        {
            "group_description": "CSV data cleaning commands",
            "commands": [
                {
                    "command": ":clean_csv",
                    "function": _make_callable(clean_missing_values_command),
                    "description": "Clean missing values in a CSV file.",
                },
                {
                    "command": ":normalize_csv",
                    "function": _make_callable(normalize_data_command),
                    "description": "Normalize numerical data in a CSV file.",
                },
            ],
        },
        {
            "group_description": "Tool management commands",
            "commands": [
                {
                    "command": ":add_db_tools",
                    "function": lambda arg=None: add_db_tools(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE),
                    "description": "Add database related tools.",
                },
                {
                    "command": ":remove_db_tools",
                    "function": lambda arg=None: remove_db_tools(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE),
                    "description": "Remove database related tools.",
                },
                {
                    "command": ":add_modelling_tools",
                    "function": lambda arg=None: add_modelling_tools(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE),
                    "description": "Add machine learning modelling tools.",
                },
                {
                    "command": ":remove_modelling_tools",
                    "function": lambda arg=None: remove_modelling_tools(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE),
                    "description": "Remove machine learning modelling tools.",
                },
            ],
        },
        {
            "group_description": "Indexing and retrieval commands",
            "commands": [
                {
                    "command": ":embed",
                    "function": _make_callable(send_file_to_indexing_service),
                    "description": "Embed a file via the indexing service.",
                },
                {
                    "command": ":query",
                    "function": _make_callable(query_using_rag),
                    "description": "Query the knowledge base using RAG.",
                },
                {
                    "command": ":index",
                    "function": _make_callable(send_directory_to_indexing_service),
                    "description": "Index an entire directory.",
                },
                {
                    "command": ":semstore",
                    "function": _make_callable(semantic_store_command),
                    "description": "Interact with the semantic store.",
                },
            ],
        },
        {
            "group_description": "Development workflow commands",
            "commands": [
                {
                    "command": ":power_user",
                    "function": _make_callable(stream_code),
                    "description": "Enable power-user streaming mode.",
                },
                {
                    "command": ":design_mode",
                    "function": _make_callable(design_mode_command),
                    "description": "Switch to design mode.",
                },
                {
                    "command": ":dev_mode",
                    "function": _make_callable(dev_mode_command),
                    "description": "Switch to development mode.",
                },
                {
                    "command": ":make_commit",
                    "function": _make_callable(make_commit_command),
                    "description": "Create a git commit with staged changes.",
                },
                {
                    "command": ":rg",
                    "function": _make_callable(rip_grep_command),
                    "description": "Search project files using ripgrep.",
                },
                {
                    "command": ":screen",
                    "function": _make_callable(run_command_in_screen),
                    "description": "Run a shell command in a detached screen session.",
                },
            ],
        },
        {
            "group_description": "Social media and streaming commands",
            "commands": [
                {
                    "command": ":twitch",
                    "function": _make_callable(send_twitch_message_command),
                    "description": "Send a message to Twitch chat.",
                },
                {
                    "command": ":joke",
                    "function": _make_callable(joke_for_twitch),
                    "description": "Tell a programming joke for Twitch.",
                },
                {
                    "command": ":tweet",
                    "function": _make_callable(send_twitter_message),
                    "description": "Send a tweet via Twitter API.",
                },
                {
                    "command": ":twitch_summary",
                    "function": _make_callable(twitch_summary_command),
                    "description": "Summarize Twitch chat activity.",
                },
                {
                    "command": ":linkedin_summary",
                    "function": _make_callable(linkedin_summary_command),
                    "description": "Generate a LinkedIn post summary.",
                },
            ],
        },
    ]

    for group in command_groups:
        for mapping in group["commands"]:
            enriched_mapping = {
                **mapping,
                "group_description": group["group_description"],
            }
            _safe_register(enriched_mapping)


# ---------------------------------------------------------------------------- #
# Re-export macros utilities                                                   #
#                                                                              #
# Why alias to the *same* name?                                                #
#  1. Facade: `core.built_ins` is the public entry-point for built-in helpers  #
#     so callers can simply do `from monitor.core.built_ins import configure_macros`   #
#     instead of reaching into `lib.macros`.                                   #
#  2. Patchability: when configure_built_ins() registers a command it stores   #
#     *the current function object*.  Tests that patch                         #
#     `core.built_ins.configure_macros` (or reload_macros_command, etc.) need  #
#     that exact reference; aliasing makes it easy.                            #
#                                                                              #
# Using __all__ alone would expose the names but would NOT create new bindings #
# in this module’s namespace, so we still need the explicit assignments below. #
#                                                                              #
# DO NOT REMOVE THIS COMMENT BLOCK                                             #
# ---------------------------------------------------------------------------- #
configure_macros = configure_macros
MACRO_VALUES = MACRO_VALUES
