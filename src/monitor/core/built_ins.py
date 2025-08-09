from monitor import config 
import logging

from typing import Any, Callable, Dict, List

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
                    "function": print_interactive_commands,
                    "description": "Print the list of interactive commands.",
                },
                {
                    "command": "history",
                    "function": conversation_history_command,
                    "description": "Show conversation history.",
                },
                {
                    "command": ":history_size",
                    "function": adjust_history_size,
                    "description": "Adjust max conversation history size.",
                },
                {
                    "command": ":reset_history",
                    "function": reset_conversation_history_command,
                    "description": "Reset the conversation history.",
                },
                {
                    "command": ":trim_history",
                    "function": trim_history_command,
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
                    "function": llm_command,
                    "description": "Change the active LLM model at runtime. Usage: :llm <model> or :llm help for available models.",
                },
                {
                    "command": ":reasoning",
                    "function": reasoning_command,
                    "description": "Change reasoning effort (minimal/low/medium/high). Usage: :reasoning <level> or :reasoning help.",
                },
                {
                    "command": "macros",
                    "function": print_macros,
                    "description": "Print available macros.",
                },
                {
                    "command": ":edit_macros",
                    "function": edit_macros_command,
                    "description": "Edit global macros file (persistent across sessions). Uses your $EDITOR.",
                },
                {
                    "command": ":reload_macros",
                    "function": reload_macros_command,
                    "description": "Reload global macros from file and summarize changes.",
                },
                {
                    "command": "tools",
                    "function": lambda *_: print_tools_command(),
                    "description": "Print currently loaded tools.",
                },
                {
                    "command": ":preferences",
                    "function": lambda arg=None: open_preferences_command(),
                    "description": "Open user preferences for editing.",
                },
                {
                    "command": ":next_steps",
                    "function": next_steps,
                    "description": "Suggest next steps based on commit analysis.",
                },
            ],
        },
        {
            "group_description": "CSV data cleaning commands",
            "commands": [
                {
                    "command": ":clean_csv",
                    "function": clean_missing_values_command,
                    "description": "Clean missing values in a CSV file.",
                },
                {
                    "command": ":normalize_csv",
                    "function": normalize_data_command,
                    "description": "Normalize numerical data in a CSV file.",
                },
            ],
        },
        {
            "group_description": "Tool management commands",
            "commands": [
                {
                    "command": ":add_db_tools",
                    "function": add_db_tools,
                    "description": "Add database related tools.",
                },
                {
                    "command": ":remove_db_tools",
                    "function": remove_db_tools,
                    "description": "Remove database related tools.",
                },
                {
                    "command": ":add_modelling_tools",
                    "function": add_modelling_tools,
                    "description": "Add machine learning modelling tools.",
                },
                {
                    "command": ":remove_modelling_tools",
                    "function": remove_modelling_tools,
                    "description": "Remove machine learning modelling tools.",
                },
            ],
        },
        {
            "group_description": "Indexing and retrieval commands",
            "commands": [
                {
                    "command": ":embed",
                    "function": send_file_to_indexing_service,
                    "description": "Embed a file via the indexing service.",
                },
                {
                    "command": ":query",
                    "function": query_using_rag,
                    "description": "Query the knowledge base using RAG.",
                },
                {
                    "command": ":index",
                    "function": send_directory_to_indexing_service,
                    "description": "Index an entire directory.",
                },
                {
                    "command": ":semstore",
                    "function": semantic_store_command,
                    "description": "Interact with the semantic store.",
                },
            ],
        },
        {
            "group_description": "Development workflow commands",
            "commands": [
                {
                    "command": ":power_user",
                    "function": stream_code,
                    "description": "Enable power-user streaming mode.",
                },
                {
                    "command": ":design_mode",
                    "function": lambda arg=None: design_mode_command(),
                    "description": "Switch to design mode.",
                },
                {
                    "command": ":dev_mode",
                    "function": lambda arg=None: dev_mode_command(),
                    "description": "Switch to development mode.",
                },
                {
                    "command": ":make_commit",
                    "function": make_commit_command,
                    "description": "Create a git commit with staged changes.",
                },
                {
                    "command": ":rg",
                    "function": rip_grep_command,
                    "description": "Search project files using ripgrep.",
                },
                {
                    "command": ":screen",
                    "function": run_command_in_screen,
                    "description": "Run a shell command in a detached screen session.",
                },
            ],
        },
        {
            "group_description": "Social media and streaming commands",
            "commands": [
                {
                    "command": ":twitch",
                    "function": send_twitch_message_command,
                    "description": "Send a message to Twitch chat.",
                },
                {
                    "command": ":joke",
                    "function": joke_for_twitch,
                    "description": "Tell a programming joke for Twitch.",
                },
                {
                    "command": ":tweet",
                    "function": send_twitter_message,
                    "description": "Send a tweet via Twitter API.",
                },
                {
                    "command": ":twitch_summary",
                    "function": twitch_summary_command,
                    "description": "Summarize Twitch chat activity.",
                },
                {
                    "command": ":linkedin_summary",
                    "function": linkedin_summary_command,
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
