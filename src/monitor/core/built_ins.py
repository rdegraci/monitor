from monitor import config 
import logging

from typing import Any, Callable, Dict, List, cast
import inspect

from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE

from monitor.lib.macros import print_macros, configure_macros, MACRO_VALUES
from monitor.core.conversation import adjust_history_size, conversation_history_command
from monitor.core.commands import print_terminal_commands
from monitor.core.commit import make_commit_command
from monitor.core.internalize_commands import rip_grep_command
from monitor.core.modes import design_mode_command, dev_mode_command

from monitor.lib.built_ins_utils import append_function_to_built_ins
from monitor.lib.commit_analysis import next_steps
from monitor.lib.git import get_default_branch
from monitor.lib.built_in_commands import clean_missing_values_command, normalize_data_command
from monitor.lib.status_line import status_line_command
from monitor.lib.built_in_commands import (
    break_chain_command,
    edit_function_keys_command,
    linkedin_summary_command,
    open_preferences_command,
    print_tools_command,
    activity_command,
    sessions_command,
    reset_conversation_history_command,
    twitch_summary_command,
    edit_macros_command,
    reload_macros_command,
    llm_command,
    copy_code_command,
    cost_debug_command,
    dump_history_command,
    fuel_debug_command,
    dump_metrics_command,
    less_command,
    load_history_command,
    max_tokens_command,
    save_response_command,
    settings_command,
    reasoning_command,
    ttl_command,
    compact_command,
    wiki_fix_command,
    wiki_init_command,
    wiki_lint_command,
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
        def varargs_wrapper(arg: Any = None) -> Any:
            try:
                if arg is None:
                    return func()
                return func(arg)
            except TypeError:
                # Fallback for callables that still error when given the argument
                return func()
        return varargs_wrapper

    # If the function accepts no positional parameters
    if len(positional_params) == 0:
        def noarg_wrapper(arg: Any = None) -> Any:
            return func()
        return noarg_wrapper

    # If the function accepts exactly one positional parameter
    if len(positional_params) == 1:
        def singlearg_wrapper(arg: Any = None) -> Any:
            try:
                if arg is None:
                    return func()
                return func(arg)
            except TypeError:
                # Preserve forgiving behavior in case the underlying function
                # chooses to raise when called with an argument.
                return func()
        return singlearg_wrapper

    # Function requires more than one positional parameter; require explicit adapter.
    def error_wrapper(arg: Any = None) -> Any:
        raise TypeError(
            f"Function '{getattr(func, '__name__', str(func))}' requires more than one positional "
            "argument. Register an explicit adapter (e.g., a lambda) when adding to built-ins."
        )

    return error_wrapper


def _safe_register(mapping: Dict[str, Callable[..., Any]]) -> None:
    """
    Register a command-function mapping with the built-ins registry safely.

    The helper logs successes and prints errors without interrupting
    the registration flow.

    Args:
        mapping: A built-in command descriptor, typically containing
            `command`, `function`, `description`, and `group_description`.
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
    is provided, the main branch is auto-detected (the repo's default branch). When
    both are provided, calls next_steps(branch, main_branch).

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
                "Usage: : (or /) next_steps <branch> [<main_branch>]\n"
                "Description: Suggest next steps based on commit analysis. If <main_branch> is omitted, the repo's default branch is auto-detected.\n"
                "Examples:\n"
                "  :next_steps my-feature\n"
                "  :next_steps my-feature main\n"
                "  :next_steps bugfix/issue-123 develop"
            )
            return
    if arg is None:
        print_colored_error("Usage: : (or /) next_steps <branch> [<main_branch>]")
        return
    try:
        text = str(arg).strip()
    except Exception:
        print_colored_error("Usage: : (or /) next_steps <branch> [<main_branch>]")
        return
    if not text:
        print_colored_error(
            "Usage: : (or /) next_steps <branch> [<main_branch>]\n"
            'Description: Suggest next steps based on commit analysis. If <main_branch> is omitted, the repository default branch is auto-detected.\n'
            "Examples:\n"
            "  :next_steps my-feature\n"
            "  :next_steps my-feature main\n"
            "  :next_steps bugfix/issue-123 develop"
        )
        return
    parts = text.split()
    if len(parts) == 1:
        branch = parts[0]
        main_branch = get_default_branch()
    elif len(parts) == 2:
        branch, main_branch = parts
    else:
        print_colored_error(
            "Usage: : (or /) next_steps <branch> [<main_branch>]\n"
            'Description: Suggest next steps based on commit analysis. If <main_branch> is omitted, the repository default branch is auto-detected.\n'
            "Examples:\n"
            "  :next_steps my-feature\n"
            "  :next_steps my-feature main\n"
            "  :next_steps bugfix/issue-123 develop"
        )
        return
    next_steps(branch, main_branch)


def tasks_command(arg: Any = None) -> None:
    """Print the current session's task plan, highest priority first.

    Reads the same per-session plan the model manages via the todo tools, so the
    user can see what's being tracked. Takes no arguments.
    """
    import json
    from monitor.lib.todo import get_task_context, list_todos

    try:
        items = json.loads(list_todos())
    except (json.JSONDecodeError, TypeError):
        items = []
    try:
        context = json.loads(get_task_context())
    except (json.JSONDecodeError, TypeError):
        context = {}

    if not items:
        print("No tasks for this session.")
    else:
        print(f"Plan ({len(items)} item{'s' if len(items) != 1 else ''}):")
        for entry in items:
            status = entry.get("status", "")
            priority = entry.get("priority", 0)
            item = entry.get("item", "")
            task_id = entry.get("id", "")
            print(f"  [{status}] P{priority} {item}  ({task_id})")
            notes = entry.get("notes", "")
            if notes:
                print(f"      notes: {notes}")

    criteria = context.get("acceptance_criteria") or []
    if criteria:
        print("Acceptance criteria:")
        for item in criteria:
            print(f"  - {item}")

    checkpoint = context.get("checkpoint") or {}
    if checkpoint:
        print("Checkpoint:")
        print(f"  summary: {checkpoint.get('summary', '')}")
        print(f"  next: {checkpoint.get('next_step', '')}")
        blockers = checkpoint.get("blockers", "")
        if blockers:
            print(f"  blockers: {blockers}")

    scope_changes = context.get("scope_changes") or []
    if scope_changes:
        print("Scope changes:")
        for entry in scope_changes[-3:]:
            tag = "material" if entry.get("material", True) else "minor"
            print(f"  - [{tag}] {entry.get('summary', '')}")


def clear_tasks_command(arg: Any = None) -> None:
    """Clear the current session's task plan."""
    from monitor.lib.todo import clear_todos

    clear_todos()
    print("Cleared the session task plan.")


def configure_built_ins() -> None:
    """
    Register all built-in commands required by the application.

    This function can be called multiple times, but it appends registrations
    to the built-ins registry and does not deduplicate existing entries.
    """
    command_groups: List[Dict[str, Any]] = [
        {
            "group_description": "General utility commands",
            "commands": [
                {
                    "command": "commands",
                    "function": _make_callable(print_terminal_commands),
                    "description": "List terminal/internal catalog names (llm<, directive<, …). Prefer :help for built-in discovery.",
                },
                {
                    "command": "history",
                    "function": lambda arg=None: conversation_history_command(arg, 10),
                    "description": "Show conversation history.",
                },
                {
                    "command": "history_size",
                    "function": lambda arg=None: adjust_history_size(
                        int(arg) if arg and str(arg).strip() else 0,
                        config.CONVERSATION_HISTORY,
                        config.CONVERSATION_MAX_SIZE or 0,
                        print,
                        COLOR_WARNING_FUNCS,
                        logger,
                        config,
                    ),
                    "description": "Adjust max conversation history size.",
                },
                {
                    "command": "llm",
                    "function": _make_callable(llm_command),
                    "description": "Change the active LLM model at runtime. Usage: : (or /) llm <model> or : (or /) llm help for available models.",
                },
                {
                    "command": "model",
                    "function": _make_callable(llm_command),
                    "description": "Alias for :llm. Usage: :model <model> or :model help.",
                },
                {
                    "command": "reasoning",
                    "function": _make_callable(reasoning_command),
                    "description": "Change reasoning effort (minimal/low/medium/high/xhigh). Usage: : (or /) reasoning <level> or : (or /) reasoning help.",
                },
                {
                    "command": "ttl",
                    "function": _make_callable(ttl_command),
                    "description": "Configure the Anthropic prompt-cache TTL (5 or 60 minutes). Usage: : (or /) ttl <minutes> or : (or /) ttl for help.",
                },
                {
                    "command": "max_tokens",
                    "function": _make_callable(max_tokens_command),
                    "description": "Cap output tokens for non-reasoning model calls. Usage: : (or /) max_tokens <N> or : (or /) max_tokens for help.",
                },
                {
                    "command": "macros",
                    "function": _make_callable(print_macros),
                    "description": "Print available macros.",
                },
                {
                    "command": "edit_macros",
                    "function": _make_callable(edit_macros_command),
                    "description": "Edit global macros file (persistent across sessions). Uses your $EDITOR.",
                },
                {
                    "command": "edit_function_keys",
                    "function": _make_callable(edit_function_keys_command),
                    "description": "Edit function keys file (persistent across sessions). Uses your $EDITOR.",
                },
                {
                    "command": "reload_macros",
                    "function": _make_callable(reload_macros_command),
                    "description": "Reload global macros from file and summarize changes.",
                },
                {
                    "command": "tools",
                    "function": _make_callable(print_tools_command),
                    "description": "Show or set the tool profile (:tools, :tools list, :tools coding, :tools catalog, :tools tokens).",
                },
                {
                    "command": "activity",
                    "function": _make_callable(activity_command),
                    "description": "Show or toggle live turn/tool activity feedback (:activity on|off|toggle).",
                },
                {
                    "command": "status",
                    "function": _make_callable(status_line_command),
                    "description": "Show or set status-line detail (:status minimal|coding|debug).",
                },
                {
                    "command": "sessions",
                    "function": _make_callable(sessions_command),
                    "description": "Print the five most recent session folder paths.",
                },
                {
                    "command": "settings",
                    "function": _make_callable(settings_command),
                    "description": "Dump the live runtime configuration settings as JSON.",
                },
                {
                    "command": "preferences",
                    "function": _make_callable(open_preferences_command),
                    "description": "Open user preferences for editing.",
                },
                {
                    "command": "tasks",
                    "function": _make_callable(tasks_command),
                    "description": "Show the current session's task plan (the list the model manages via task tools).",
                },
                {
                    "command": "clear_tasks",
                    "function": _make_callable(clear_tasks_command),
                    "description": "Clear the current session's task plan.",
                },
                {
                    "command": "next_steps",
                    "function": _make_callable(next_steps_command),
                    "description": "Suggest next steps based on commit analysis.",
                },
            ],
        },
        {
            "group_description": "Session persistence",
            "commands": [
                {
                    "command": "reset_history",
                    "function": _make_callable(reset_conversation_history_command),
                    "description": "Reset the conversation history.",
                },
                {
                    "command": "break_chain",
                    "function": _make_callable(break_chain_command),
                    "description": "Break the Responses chain (clear RESPONSE_ID) but KEEP conversation history, dropping billed context back under the 2x cost cliff.",
                },
                {
                    "command": "compact",
                    "function": _make_callable(compact_command),
                    "description": "Compact older conversation history into a summary (usage: :compact).",
                },
                {
                    "command": "dump_history",
                    "function": _make_callable(dump_history_command),
                    "description": "Write full conversation history as JSON. Usage: : (or /) dump_history <path>.",
                },
                {
                    "command": "load_history",
                    "function": _make_callable(load_history_command),
                    "description": "Replace current conversation with a saved JSON transcript. Usage: : (or /) load_history <path>.",
                },
            ],
        },
        {
            "group_description": "Diagnostics & metrics",
            "commands": [
                {
                    "command": "cost_debug",
                    "function": _make_callable(cost_debug_command),
                    "description": "Dump per-turn cost-tracking state and flag invariant violations.",
                },
                {
                    "command": "fuel_debug",
                    "function": _make_callable(fuel_debug_command),
                    "description": "Dump fuel-budget state and suggest a MODEL_TOKEN_RATE_PER_MTOK value.",
                },
                {
                    "command": "dump_metrics",
                    "function": _make_callable(dump_metrics_command),
                    "description": "Write session metrics (cost, tokens, tool calls, loop trips) as JSON. Usage: : (or /) dump_metrics <path>.",
                },
            ],
        },
        {
            "group_description": "Response helpers",
            "commands": [
                {
                    "command": "less",
                    "function": _make_callable(less_command),
                    "description": "Re-display the last assistant response paged through less.",
                },
                {
                    "command": "save_response",
                    "function": _make_callable(save_response_command),
                    "description": "Save the last assistant response to a file. Usage: : (or /) save_response [path]. No arg → cwd/response-<ts>.md.",
                },
                {
                    "command": "copy_code",
                    "function": _make_callable(copy_code_command),
                    "description": "Copy a code block from the last response to the clipboard. Usage: : (or /) copy_code [N | all]. No arg → first block.",
                },
                {
                    "command": "cc",
                    "function": _make_callable(copy_code_command),
                    "description": "Alias for :copy_code. Usage: :cc [N | all].",
                },
            ],
        },
        {
            "group_description": "CSV data cleaning commands",
            "commands": [
                {
                    "command": "clean_csv",
                    "function": _make_callable(clean_missing_values_command),
                    "description": "Clean missing values in a CSV file.",
                },
                {
                    "command": "normalize_csv",
                    "function": _make_callable(normalize_data_command),
                    "description": "Normalize numerical data in a CSV file.",
                },
            ],
        },
        {
            "group_description": "Tool management commands EXPERIMENTAL",
            "commands": [
                {
                    "command": "add_db_tools",
                    "function": lambda arg=None: add_db_tools(cast(List[Dict[str, Any]], TOOL_DESCRIPTIONS), cast(List[Dict[str, Any]], GEMINI_TOOL_DESCRIPTIONS), cast(Dict[str, bool], TOOL_STATE)),
                    "description": "Add database related tools.",
                },
                {
                    "command": "remove_db_tools",
                    "function": lambda arg=None: remove_db_tools(TOOL_DESCRIPTIONS, TOOL_STATE),
                    "description": "Remove database related tools.",
                },
                {
                    "command": "add_modelling_tools",
                    "function": lambda arg=None: add_modelling_tools(cast(List[Dict[str, Any]], TOOL_DESCRIPTIONS), cast(List[Dict[str, Any]], GEMINI_TOOL_DESCRIPTIONS), cast(Dict[str, bool], TOOL_STATE)),
                    "description": "Add machine learning modelling tools.",
                },
                {
                    "command": "remove_modelling_tools",
                    "function": lambda arg=None: remove_modelling_tools(cast(List[Dict[str, Any]], TOOL_DESCRIPTIONS), cast(Dict[str, bool], TOOL_STATE)),
                    "description": "Remove machine learning modelling tools.",
                },
            ],
        },
        {
            "group_description": "Indexing and retrieval commands (Experimental)",
            "commands": [
                {
                    "command": "embed",
                    "function": _make_callable(send_file_to_indexing_service),
                    "description": "Embed a file via the indexing service.",
                },
                {
                    "command": "query",
                    "function": _make_callable(query_using_rag),
                    "description": "Query the knowledge base using RAG.",
                },
                {
                    "command": "index",
                    "function": _make_callable(send_directory_to_indexing_service),
                    "description": "Index an entire directory.",
                },
                {
                    "command": "semstore",
                    "function": _make_callable(semantic_store_command),
                    "description": "Interact with the semantic store.",
                },
            ],
        },
        {
            "group_description": "Development workflow commands",
            "commands": [
                {
                    "command": "power_user",
                    "function": _make_callable(stream_code),
                    "description": "Enable power-user streaming mode. <file_path>:<prompt>",
                },
                {
                    "command": "design_mode",
                    "function": _make_callable(design_mode_command),
                    "description": "Switch to design mode.",
                },
                {
                    "command": "dev_mode",
                    "function": _make_callable(dev_mode_command),
                    "description": "Switch to development mode.",
                },
                {
                    "command": "wiki_init",
                    "function": _make_callable(wiki_init_command),
                    "description": "Draft a project-aware INDEX.md for the configured project wiki.",
                },
                {
                    "command": "wiki_lint",
                    "function": _make_callable(wiki_lint_command),
                    "description": "Run the configured project wiki linter and print a report.",
                },
                {
                    "command": "wiki_fix",
                    "function": _make_callable(wiki_fix_command),
                    "description": "Preview a minimal wiki fix for a stored lint finding.",
                },
                {
                    "command": "make_commit",
                    "function": lambda arg=None: make_commit_command(arg, print_func=print),
                    "description": "Create a git commit with staged changes.",
                },
                {
                    "command": "rg",
                    "function": lambda arg=None: rip_grep_command(arg, print_func=print),
                    "description": "Search project files using ripgrep.",
                },
                {
                    "command": "agent",
                    "function": _make_callable(run_command_in_screen),
                    "description": "Manage detached agent (GNU screen) sessions: list / logs / logfile / attach / kill / send / spawn. Type :agent or /agent for subcommand help.",
                },
            ],
        },
        {
            "group_description": "Social media and streaming commands",
            "commands": [
                {
                    "command": "twitch",
                    "function": _make_callable(send_twitch_message_command),
                    "description": "Send a message to Twitch chat.",
                },
                {
                    "command": "joke",
                    "function": _make_callable(joke_for_twitch),
                    "description": "Tell a programming joke for Twitch.",
                },
                {
                    "command": "tweet",
                    "function": _make_callable(send_twitter_message),
                    "description": "Send a tweet via Twitter API.",
                },
                {
                    "command": "twitch_summary",
                    "function": _make_callable(twitch_summary_command),
                    "description": "Summarize Twitch chat activity.",
                },
                {
                    "command": "linkedin_summary",
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
