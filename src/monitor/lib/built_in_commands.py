import os
import logging
from monitor import config
import copy

from typing import Any, Dict
from colored import attr, fg
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import BashLexer, MarkdownLexer

from monitor.lib.summarizers import summarize_conversation_for_twitch
from monitor.lib.summarizers import summarize_conversation_for_linkedin
from monitor.lib.external_services import (
    send_twitch_message_command,
    joke_for_twitch,
    send_twitter_message,
    send_file_to_indexing_service,
    send_artifact,
    send_linkedin_message,
)

from monitor.lib.preferences import open_preferences_editor
from monitor.lib.system_prompt import SYSTEM_PROMPT
from monitor.lib.tool_loading import list_tools
from monitor.lib.display_output import print_colored_error
from monitor.lib.colors import print_yellow
from monitor.lib.history import adjust_history_size

logger = logging.getLogger(__name__)


def handle_cd_command(args: str) -> str:
    """
    Change the current working directory.

    Args:
        args (str): Path to directory
    Returns:
        str: New working directory on success
    Raises:
        FileNotFoundError, NotADirectoryError, PermissionError
    """
    try:
        os.chdir(os.path.expanduser(args))
        cwd = os.getcwd()
        return cwd
    except FileNotFoundError:
        logger.error(f"Directory not found: {args}")
        return f"Directory not found: {args}"
    except NotADirectoryError:
        logger.error(f"Not a directory: {args}")
        return f"Not a directory: {args}"
    except PermissionError:
        logger.error(f"Permission denied: {args}")
        return f"Permission denied: {args}"


def clear_screen() -> None:
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def print_debug(command_to_run: Any, debug: bool = True) -> None:
    """Print debug information if DEBUG mode is on."""
    if debug:
        logger.debug(command_to_run)


def clean_missing_values_command(args: Dict[str, Any]) -> Any:
    """Clean missing values in the specified file."""
    from preprocessing import clean_missing_values

    file_path = args.get("file_path")
    fill_value = args.get("fill_value", 0)
    try:
        result = clean_missing_values(file_path, fill_value)
        return result
    except Exception as exc:
        logger.error(f"Error in clean_missing_values_command: {exc}", exc_info=True)
        return f"Error cleaning missing values: {exc}"


def normalize_data_command(args: Dict[str, Any]) -> Any:
    """Normalize data in the specified file."""
    from preprocessing import normalize_data

    file_path = args.get("file_path")
    method = args.get("method", "standard")
    try:
        result = normalize_data(file_path, method)
        return result
    except Exception as exc:
        logger.error(f"Error in normalize_data_command: {exc}", exc_info=True)
        return f"Error normalizing data: {exc}"


def deploy_model_command(args: Dict[str, Any]) -> Any:
    """Deploy specified model to an endpoint."""
    from deployment import deploy_model

    model_path = args.get("model_path")
    endpoint_url = args.get("endpoint_url")
    deployment_platform = args.get("deployment_platform")
    try:
        result = deploy_model(model_path, endpoint_url, deployment_platform)
        return result
    except Exception as exc:
        logger.error(f"Error in deploy_model_command: {exc}", exc_info=True)
        return f"Error deploying model: {exc}"


def monitor_model_performance_command(args: Dict[str, Any]) -> Any:
    """Monitor performance of deployed model."""
    from deployment import monitor_model_performance

    endpoint_url = args.get("endpoint_url")
    metrics_to_track = args.get("metrics_to_track", [])
    try:
        result = monitor_model_performance(endpoint_url, metrics_to_track)
        return result
    except Exception as exc:
        logger.error(f"Error in monitor_model_performance_command: {exc}", exc_info=True)
        return f"Error monitoring model performance: {exc}"


def reset_conversation_history_command(arg=None):
    try:
        config.CONVERSATION_HISTORY.clear()
        config.CONVERSATION_HISTORY.append({"role": "system", "content": SYSTEM_PROMPT})
        config.TOTAL_TOKEN_COUNT = 0
        print("Conversation history was reset to initial system prompt.")
    except Exception as e:
        logger.error(f"Failed to reset conversation history: {e}", exc_info=True)


def twitch_summary_command(arg=None):
    """
    Summarize the conversation history for Twitch broadcasting.

    Calls summarize_conversation_for_twitch on the current conversation history and prints the result.
    """
    try:
        summary = summarize_conversation_for_twitch(
            config.CONVERSATION_HISTORY, config.MODEL
        )
        if not summary:
            return
        print(summary)
        send_twitch_message_command(summary)
    except Exception as e:
        logger.error(f"Failed to summarize conversation for Twitch: {e}", exc_info=True)


def linkedin_summary_command(arg=None):
    """
    Summarize the conversation history for LinkedIn broadcasting.

    Calls summarize_conversation_for_linkedin on the current conversation history and prints the result.
    If send_linkedin_message is available, broadcasts the summary to LinkedIn.
    """
    try:
        summary = summarize_conversation_for_linkedin(
            config.CONVERSATION_HISTORY, config.MODEL
        )
        if not summary:
            return
        print(summary)
        if send_linkedin_message:
            send_linkedin_message(summary)
    except Exception as e:
        logger.error(f"Failed to summarize conversation for LinkedIn: {e}", exc_info=True)


def open_preferences_command():
    result = open_preferences_editor(config.PREFERENCE_PROMPT_FILE)
    print(result)


def edit_macros_command(arg=None):
    """
    Edit global macros, optionally accepting and ignoring a dispatcher argument.

    This allows the function to match the expected function signature of the built-in command dispatcher,
    which may pass an argument even if unused.
    """
    from monitor.lib.macros import open_macros_editor
    result = open_macros_editor()
    if result:
        print(result)


def reload_macros_command(arg: Any = None) -> None:
    """Reload macros from configuration and report the summary of changes.

    Args:
        arg (Any, optional): Ignored dispatcher argument included for interface
            compatibility. Defaults to ``None``.

    Returns:
        None
    """
    from monitor.lib.macros import configure_macros, MACRO_VALUES

    try:
        # Snapshot macros before reload
        try:
            old_macros = copy.deepcopy(MACRO_VALUES)
        except Exception:
            old_macros = dict(MACRO_VALUES)

        # Reload macros (updates happen in-place)
        configure_macros()

        # Snapshot macros after reload
        try:
            new_macros = copy.deepcopy(MACRO_VALUES)
        except Exception:
            new_macros = dict(MACRO_VALUES)

        old_keys = set(old_macros.keys())
        new_keys = set(new_macros.keys())
        added = sorted(new_keys - old_keys)
        removed = sorted(old_keys - new_keys)
        changed = sorted(
            [k for k in (old_keys & new_keys) if old_macros[k] != new_macros[k]]
        )

        summary_lines = []
        if added:
            summary_lines.append("Added macros: " + ", ".join(added))
        if removed:
            summary_lines.append("Removed macros: " + ", ".join(removed))
        if changed:
            summary_lines.append("Changed macros: " + ", ".join(changed))

        print("Macros were reloaded successfully.")
        if summary_lines:
            print("; ".join(summary_lines))
        else:
            print("No macros added, removed, or changed.")
    except Exception as e:
        print_colored_error(f"Failed to reload macros: {e}")
        logger.error(f"Failed to reload macros: {e}", exc_info=True)


def print_tools_command():
    from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS, TOOL_STATE

    # Debug logging: log types and (truncated) contents of TOOL_DESCRIPTIONS and TOOL_STATE.
    # Helper to truncate large structures for preview.
    def _truncate_repr(obj, maxlen=500):
        try:
            rep = repr(obj)
        except Exception as e:
            rep = f"repr-failed({e})"
        if len(rep) > maxlen:
            return rep[:maxlen] + "... [truncated]"
        return rep

    # TOOL_DESCRIPTIONS type and truncated content
    logger.debug(f"TOOL_DESCRIPTIONS type: {type(TOOL_DESCRIPTIONS)} - preview: {_truncate_repr(TOOL_DESCRIPTIONS)}")
    if not isinstance(TOOL_DESCRIPTIONS, list):
        logger.warning("TOOL_DESCRIPTIONS is not a list!")

    # TOOL_STATE type and truncated content
    logger.debug(f"TOOL_STATE type: {type(TOOL_STATE)} - preview: {_truncate_repr(TOOL_STATE)}")
    if not isinstance(TOOL_STATE, dict):
        logger.warning("TOOL_STATE is not a dict!")

    tools = list_tools(TOOL_DESCRIPTIONS, TOOL_STATE)
    logger.debug(f"tools after list_tools() type: {type(tools)} - preview: {_truncate_repr(tools)}")
    if not isinstance(tools, dict):
        logger.warning("tools is not a dict after list_tools()!")

    for name, info in tools.items():
        print(f"Tool: {name}")
        print(f"  Description: {info['description']}")
        print(f"  Active: {info['active']}")
        print("-" * 40)

def llm_command(arg: str = None) -> None:
    """
    Change the active LLM model at runtime.

    Usage:
        :llm <model>
        :llm help

    With no argument or 'help', prints available models and usage.
    With a valid model name or shorthand, sets the model using config.set_model(arg).

    Args:
        arg: Model (shorthand or full name) to set, or 'help'/'?' for info.

    Shows current model and settings after changing, or prints an error.
    """
    try:
        arg_provided = arg is not None and str(arg).strip() != ""
        if not arg_provided or str(arg).strip().lower() in {"help", "?", "-h", "--help"}:
            print("Dynamically set the active LLM model for completions.")
            print("Usage: :llm <modelname>")
            print("Available models:")
            mapping = getattr(config, "model_mapping", {})
            for k, v in mapping.items():
                current = ""
                if config.MODEL == v:
                    current = " (active)"
                print(f"  {k:16} -> {v}{current}")
            print("Use the key (e.g. 'o3') of the model you wish to set as active.")
            return

        model_arg = str(arg).strip()
        config.set_model(model_arg)
        config.configure_subsystems()
        print_yellow(
            f"Active model set to: {config.MODEL}\n"
            f"MODEL_CONTEXT_WINDOW = {config.MODEL_CONTEXT_WINDOW}\n"
            f"MODEL_OUTPUT_WINDOW = {config.MODEL_OUTPUT_WINDOW}\n"
            f"MODEL_MAX_TPM = {config.MODEL_MAX_TPM}\n"
            f"CONVERSATION_MAX_SIZE = {config.CONVERSATION_MAX_SIZE}"
        )
    except Exception as e:
        print_colored_error(f"Could not set LLM model: {e}")
        mapping = getattr(config, "model_mapping", {})
        if mapping:
            print("Available models:")
            for k, v in mapping.items():
                print(f"  {k:16} -> {v}")
        print("Usage: :llm <modelname>. See ':llm help'.")

def trim_history_command(arg: str) -> None:
    """Trim the last N items from conversation history.

    Args:
        arg: A string representing the number of items to remove from history.

    Behavior:
        - Parses arg to an integer (N). If invalid or not provided, prints an error.
        - If N <= 0, prints an error.
        - If N > len(config.CONVERSATION_HISTORY), removes all history and warns user.
        - Otherwise, pops last N elements from monitor.config.CONVERSATION_HISTORY.
        - Prints or logs how many items were removed.
    """
    if arg is None or not str(arg).strip():
        print_colored_error("You must provide a count for how many history items to remove.")
        return
    try:
        n = int(str(arg).strip())
    except Exception:
        print_colored_error(f"Cannot parse number of items to remove from history: '{arg}'")
        return
    if n <= 0:
        print_colored_error("Number of items to remove must be positive.")
        return
    size = len(config.CONVERSATION_HISTORY)
    if n > size:
        removed = size
        config.CONVERSATION_HISTORY.clear()
        logger.warning("Requested to remove %s items, but history contains only %s items. History cleared.", n, size)
        print(f"History contained {size} items. All were removed.")
    else:
        removed = n
        for _ in range(n):
            config.CONVERSATION_HISTORY.pop()
        print(f"Removed last {removed} item(s) from conversation history.")
        logger.info("Removed last %s item(s) from conversation history.", removed)


def compact_history_command(
    arg,  # The integer argument N, as string
    config,
    print_func,
    color_warning_funcs,
    logger
):
    try:
        n = int(arg)
        result = adjust_history_size(
            n,
            config.CONVERSATION_HISTORY,
            config.CONVERSATION_MAX_SIZE,
            print_func,
            color_warning_funcs,
            logger,
        )
        config.CONVERSATION_MAX_SIZE = result  # Update for consistency
    except Exception as e:
        print_func(f"Error: {e}")
