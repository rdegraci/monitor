import copy
import logging
import os
import subprocess

from typing import Any, Dict

import appdirs
from colored import attr, fg
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import BashLexer, MarkdownLexer

from monitor import config
from monitor.function_keys_loader import load_function_keys_config
from monitor.lib.colors import print_yellow
from monitor.lib.display_output import print_colored_error
from monitor.lib.external_services import (
    joke_for_twitch,
    send_artifact,
    send_file_to_indexing_service,
    send_linkedin_message,
    send_twitter_message,
    send_twitch_message_command,
)
# Note: ``adjust_history_size`` is imported lazily inside the call site below
# to avoid a module-load cycle when something imports ``monitor.lib.history``
# directly (e.g., tests). See the analogous note in monitor/lib/redis_utils.py.
from monitor.lib.keyboard import configure_function_key_insertions
from monitor.lib.preferences import open_preferences_editor
from monitor.lib.summarizers import summarize_conversation_for_linkedin
from monitor.lib.summarizers import summarize_conversation_for_twitch
from monitor.lib.system_prompt import build_system_prompt
from monitor.lib.tool_loading import list_tools

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


def clean_missing_values_command(args: Any) -> Any:
    """Clean missing values in the specified file.

    This command accepts multiple invocation styles to be flexible with the
    command dispatcher:

    - clean_missing_values_command(None)
        Prints usage/help.

    - clean_missing_values_command("path/to/file.csv")
        Uses the given string as the file_path and a default fill_value of 0.

    - clean_missing_values_command({"file_path": "path/to/file.csv", "fill_value": 1})
        Uses a dict to specify the file_path and optional fill_value.

    - clean_missing_values_command({"help": True})
        Prints usage/help.

    Behavior:
        - When called with None, 'help', '?', or a dict with help=True, prints usage and returns None.
        - When called with a string, treats it as a file_path and uses fill_value=0.
        - When called with a dict, requires 'file_path' key unless help=True is provided.
        - If file_path is missing in dict mode, prints a colored error via print_colored_error.
        - Preserves existing logging and exception handling: errors are logged with exc_info=True
          and an error message string is returned on failure.

    Args:
        args: Either None, a help string ('help', '?'), a file path string, or a dict
              with keys 'file_path' (required) and optional 'fill_value' (defaults to 0).

    Returns:
        The result of preprocessing.clean_missing_values(file_path, fill_value) on success,
        or an error message string on failure, or None when showing help.
    """
    from monitor.lib.preprocessing import clean_missing_values

    # Helper: usage message
    usage = (
        "Usage: clean_missing_values_command(<file_path>)\n"
        "   or clean_missing_values_command({'file_path': <path>, 'fill_value': <value>})\n"
        "If 'help' or None is provided, this message is printed."
    )

    # Normalize None or help-like strings
    if args is None:
        print(usage)
        return None

    if isinstance(args, str):
        arg_str = args.strip()
        if not arg_str or arg_str.lower() in {"help", "?", "-h", "--help"}:
            print(usage)
            return None
        file_path = arg_str
        fill_value = 0
    elif isinstance(args, dict):
        # If help requested in dict form
        if args.get("help"):
            print(usage)
            return None
        file_path = args.get("file_path")
        fill_value = args.get("fill_value", 0)
        if not file_path:
            print_colored_error("Missing required parameter: 'file_path'")
            logger.error("Missing required parameter 'file_path' in clean_missing_values_command call.")
            return None
    else:
        print_colored_error("Invalid argument type. Provide a file path string or a dict with 'file_path'.")
        logger.error("Invalid argument type for clean_missing_values_command: %s", type(args))
        return None

    try:
        result = clean_missing_values(file_path, fill_value)
        return result
    except Exception as exc:
        logger.error(f"Error in clean_missing_values_command: {exc}", exc_info=True)
        return f"Error cleaning missing values: {exc}"


def normalize_data_command(args: Any) -> Any:
    """Normalize data in the specified file.

    This command accepts multiple invocation styles to be flexible with the
    command dispatcher:

    - normalize_data_command(None)
        Prints usage/help.

    - normalize_data_command("path/to/file.csv")
        Uses the given string as the file_path and a default method of 'standard'.

    - normalize_data_command({"file_path": "path/to/file.csv", "method": "minmax"})
        Uses a dict to specify the file_path and optional method.

    - normalize_data_command({"help": True})
        Prints usage/help.

    Behavior:
        - When called with None, 'help', '?', or a dict with help=True, prints usage and returns None.
        - When called with a string, treats it as a file_path and uses method='standard'.
        - When called with a dict, requires 'file_path' key unless help=True is provided.
        - If file_path is missing in dict mode, prints a colored error via print_colored_error.
        - Preserves existing logging and exception handling: errors are logged with exc_info=True
          and an error message string is returned on failure.

    Args:
        args: Either None, a help string ('help', '?'), a file path string, or a dict
              with keys 'file_path' (required) and optional 'method' (defaults to 'standard').

    Returns:
        The result of monitor.lib.preprocessing.normalize_data(file_path, method) on success,
        or an error message string on failure, or None when showing help.
    """
    from monitor.lib.preprocessing import normalize_data

    usage = (
        "Usage: normalize_data_command(<file_path>)\n"
        "   or normalize_data_command({'file_path': <path>, 'method': <method>})\n"
        "If 'help' or None is provided, this message is printed."
    )

    if args is None:
        print(usage)
        return None

    if isinstance(args, str):
        arg_str = args.strip()
        if not arg_str or arg_str.lower() in {"help", "?", "-h", "--help"}:
            print(usage)
            return None
        file_path = arg_str
        method = "standard"
    elif isinstance(args, dict):
        if args.get("help"):
            print(usage)
            return None
        file_path = args.get("file_path")
        method = args.get("method", "standard")
        if not file_path:
            print_colored_error("Missing required parameter: 'file_path'")
            logger.error("Missing required parameter 'file_path' in normalize_data_command call.")
            return None
    else:
        print_colored_error("Invalid argument type. Provide a file path string or a dict with 'file_path'.")
        logger.error("Invalid argument type for normalize_data_command: %s", type(args))
        return None

    try:
        result = normalize_data(file_path, method)
        return result
    except Exception as exc:
        logger.error(f"Error in normalize_data_command: {exc}", exc_info=True)
        return f"Error normalizing data: {exc}"


def deploy_model_command(args: Dict[str, Any]) -> Any:
    """Deploy specified model to an endpoint."""
    from monitor.lib.deployment import deploy_model

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
    from monitor.lib.deployment import monitor_model_performance

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
        config.CONVERSATION_HISTORY.append({"role": "system", "content": build_system_prompt(session_id=getattr(config, "SESSION_ID", None))})
        config.TOTAL_TOKEN_COUNT = 0
        # :reset_history is user-explicit "start fresh" — clear the session
        # cumulative counters too so U and (~$N.NN) reset alongside.
        config.SESSION_TOTAL_TOKENS = 0
        config.SESSION_COST_USD = 0.0
        config.SESSION_COMPACTION_COUNT = 0
        config.TURN_COSTS_USD = []
        config.CURRENT_TURN_REASONING_OVERRIDE = None
        config.RESPONSE_ID = None
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


def open_preferences_command(arg=None):
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


def open_function_keys_editor(path=None):
    """Open the function keys configuration file in a text editor.

    Args:
        path: Optional path to the function keys configuration file. If not
            provided, the default configuration directory from
            ``appdirs.user_config_dir('monitor')`` is used.

    Returns:
        The path to the configuration file on success, or ``None`` on failure.
    """
    try:
        if path is None:
            path = os.path.join(appdirs.user_config_dir("monitor"), "function_keys.json")

        os.makedirs(os.path.dirname(path), exist_ok=True)

        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write("{}\n")

        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
        result = subprocess.run([editor, path], check=False)
        if result.returncode != 0:
            message = f"Editor exited with non-zero status {result.returncode}: {editor}"
            print_colored_error(message)
            logger.error(message)
            return None
        return path
    except Exception as e:
        print_colored_error(f"Failed to open function keys editor: {e}")
        logger.error(f"Failed to open function keys editor: {e}", exc_info=True)
        return None


def edit_function_keys_command(arg=None):
    """Edit grouped function key bindings and apply them after saving.

    Args:
        arg: Optional dispatcher argument. If provided as a string path, it is
            used as the function keys configuration file path.

    Returns:
        The path to the configuration file on success, or ``None`` on failure.
    """
    try:
        path = arg if isinstance(arg, str) and str(arg).strip() else None
        config_path = open_function_keys_editor(path)
        if not config_path:
            return None

        grouped_bindings = load_function_keys_config(config_path)
        configure_function_key_insertions(grouped_bindings)
        logger.info("Applied grouped function key bindings from %s", config_path)
        print(f"Function keys configuration updated and applied: {config_path}")
        return config_path
    except Exception as e:
        print_colored_error(f"Failed to edit function keys configuration: {e}")
        logger.error(f"Failed to edit function keys configuration: {e}", exc_info=True)
        return None


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


def print_tools_command(arg=None):
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

def reasoning_command(arg: str = None) -> None:
    """
    Change the reasoning effort level at runtime.

    Usage:
        :reasoning <minimal|low|medium|high>

    With no argument or 'help', prints available options, current setting, and the
    reasoning model prefix requirement.
    """
    try:
        arg_provided = arg is not None and str(arg).strip() != ""
        if not arg_provided or str(arg).strip().lower() in {"help", "?", "-h", "--help"}:
            current = getattr(config, "REASONING_EFFORT", None)
            prefix = getattr(config, "REASONING_MODEL_PREFIX", "")
            print("Set the reasoning effort level used with reasoning-capable models.")
            print("Usage: :reasoning <minimal|low|medium|high>")
            print(f"Current reasoning effort: {current}")
            print(f"Reasoning model prefix requirement: {prefix}")
            return

        value = str(arg).strip().lower()
        valid = {"minimal", "low", "medium", "high"}
        if value not in valid:
            print_colored_error("Invalid reasoning effort. Valid options: minimal, low, medium, high.")
            return

        config.REASONING_EFFORT = value
        prefix = getattr(config, "REASONING_MODEL_PREFIX", "")
        print_yellow(
            f"Reasoning effort set to: {config.REASONING_EFFORT}\n"
            f"Reasoning model prefix requirement: {prefix}\n"
            f"Active model: {config.MODEL}"
        )
        try:
            model_name = str(getattr(config, "MODEL", ""))
            prefix_str = "" if prefix is None else str(prefix)
            if prefix_str and prefix_str.lower() not in model_name.lower():
                print_yellow("Warning: Active model does not match the reasoning model prefix; the reasoning effort setting may have no effect.")
        except Exception:
            pass
    except Exception as e:
        print_colored_error(f"Could not set reasoning effort: {e}")

def _ttl_minutes_from_api_value(api_value):
    """Convert Anthropic's ``cache_control.ttl`` string ("5m" or "1h") to an
    integer-minute count for display purposes. Defaults to 60 (1h)."""
    if api_value == "5m":
        return 5
    return 60  # treats "1h" and anything unrecognized as the default


def _print_ttl_help(current_minutes):
    print("Set the Anthropic prompt-cache TTL for the system + tools breakpoints.")
    print("Usage: :ttl <minutes>")
    print("Valid values:")
    print("  :ttl 5    — 5-minute cache (write at 1.25x base input cost)")
    print("  :ttl 60   — 1-hour cache (write at 2x base input cost; wins when idle >5min)")
    print("Reads cost 0.1x base for both TTLs. The final-user-message breakpoint")
    print("stays at 5m regardless (it changes every turn).")
    print(f"Current TTL: {current_minutes} minutes.")


def ttl_command(arg: str = None) -> None:
    """
    Configure the Anthropic prompt-cache TTL at runtime.

    Usage:
        :ttl              — show help and current TTL
        :ttl <minutes>    — set to 5 or 60 minutes

    Affects only Anthropic models; OpenAI prompt caching is automatic and
    needs no directive. The final-user-message cache breakpoint stays at 5m
    regardless of this setting because it moves every turn.
    """
    current_api = getattr(config, "ANTHROPIC_CACHE_TTL", "1h")
    current_minutes = _ttl_minutes_from_api_value(current_api)

    arg_provided = arg is not None and str(arg).strip() != ""
    if not arg_provided or str(arg).strip().lower() in {"help", "?", "-h", "--help"}:
        _print_ttl_help(current_minutes)
        return

    text = str(arg).strip()
    try:
        minutes = int(text)
    except ValueError:
        print_colored_error(f"Could not parse '{text}' as an integer.")
        _print_ttl_help(current_minutes)
        return

    if minutes == 5:
        config.ANTHROPIC_CACHE_TTL = "5m"
        print_yellow("Anthropic prompt-cache TTL set to 5 minutes (system + tools breakpoints).")
    elif minutes == 60:
        config.ANTHROPIC_CACHE_TTL = "1h"
        print_yellow("Anthropic prompt-cache TTL set to 1 hour (system + tools breakpoints).")
    else:
        print_colored_error(f"Invalid value: {minutes}. Anthropic supports only 5 or 60 minutes.")
        _print_ttl_help(current_minutes)


def _print_max_tokens_help(current_value):
    print("Cap output tokens for non-reasoning model calls (max_completion_tokens).")
    print("Usage: :max_tokens <N>")
    print("Reasoning models (gpt-5-style) use REASONING_MAX_COMPLETION_TOKENS instead;")
    print("this cap does not affect them. Raise the value for long-form generation,")
    print("lower it to cut runaway tail-end completions.")
    print(f"Current cap: {current_value} tokens.")


def max_tokens_command(arg: str = None) -> None:
    """
    Configure the non-reasoning output-token cap at runtime.

    Usage:
        :max_tokens          — show help and current cap
        :max_tokens <N>      — set cap to N (positive integer)

    Affects only non-reasoning model calls. Reasoning models continue to
    use REASONING_MAX_COMPLETION_TOKENS, which is sized for chain-of-thought.
    """
    current = getattr(config, "MAX_COMPLETION_TOKENS", 8192)

    arg_provided = arg is not None and str(arg).strip() != ""
    if not arg_provided or str(arg).strip().lower() in {"help", "?", "-h", "--help"}:
        _print_max_tokens_help(current)
        return

    text = str(arg).strip()
    try:
        new_cap = int(text)
    except ValueError:
        print_colored_error(f"Could not parse '{text}' as an integer.")
        _print_max_tokens_help(current)
        return

    if new_cap < 1:
        print_colored_error(f"Invalid value: {new_cap}. Must be >= 1.")
        _print_max_tokens_help(current)
        return

    config.MAX_COMPLETION_TOKENS = new_cap
    print_yellow(f"Output-token cap set to {new_cap} (non-reasoning model calls).")


def cost_debug_command(arg: str = None) -> None:
    """Dump cost-tracking state for diagnosing the U: indicator.

    Prints SESSION_COST_USD, SESSION_TOTAL_TOKENS, the per-turn bucket
    list, the user-message count in CONVERSATION_HISTORY, and flags two
    invariants worth checking:

    - bucket_count == user_message_count: one bucket per user message.
      A mismatch means either bucket-open or bucket-pop is firing for the
      wrong messages.
    - sum(buckets) == cumulative: every cost that grew the cumulative also
      grew a bucket. A drift means the bucket-update try/except in
      token_management.py is silently swallowing exceptions on some calls.
    """
    del arg  # no arguments

    session_cost = getattr(config, "SESSION_COST_USD", 0.0) or 0.0
    session_tokens = getattr(config, "SESSION_TOTAL_TOKENS", 0) or 0
    buckets = getattr(config, "TURN_COSTS_USD", None) or []
    history = getattr(config, "CONVERSATION_HISTORY", None) or []
    user_count = sum(
        1 for m in history
        if isinstance(m, dict) and m.get("role") == "user"
    )
    bucket_sum = sum(buckets)

    print("=== Cost-tracking debug ===")
    print(f"SESSION_COST_USD:    ${session_cost:.6f}")
    print(f"SESSION_TOTAL_TOKENS: {session_tokens}")
    print(f"User messages in history: {user_count}")
    print(f"Per-turn buckets:    {len(buckets)} (sum: ${bucket_sum:.6f})")

    if buckets:
        # Pair each bucket with the corresponding user message preview, so
        # we can spot duplicates, synthetic prefixes, or other anomalies.
        # i-th user message in CONVERSATION_HISTORY pairs with bucket i.
        user_msgs = [
            m for m in history
            if isinstance(m, dict) and m.get("role") == "user"
        ]
        print("Bucket contents (index: value  len=N  ...tail of user message):")
        for i, val in enumerate(buckets):
            marker = "  <-- ZERO" if val == 0 else ""
            content = ""
            if i < len(user_msgs):
                raw = user_msgs[i].get("content", "")
                if not isinstance(raw, str):
                    raw = str(raw)
                flat = raw.replace("\n", " ").strip()
                length = len(flat)
                # Most user messages here are prepended with a long shared
                # prefix (MONITOR.md project instructions). Showing only
                # the *tail* makes the per-message difference visible
                # instead of getting eaten by the shared prefix.
                tail = flat[-100:] if length > 100 else flat
                content = f"  len={length}  ...{tail!r}"
            print(f"  [{i:3d}]: ${val:.6f}{marker}{content}")
    else:
        print("Bucket list is empty.")

    print()
    print("--- Invariant checks ---")
    if len(buckets) == user_count:
        print(f"OK  bucket_count == user_message_count ({user_count})")
    else:
        print_colored_error(
            f"MISMATCH bucket_count={len(buckets)} but user_message_count={user_count} "
            "— bucket-open or bucket-pop is firing for the wrong messages."
        )

    drift = session_cost - bucket_sum
    if abs(drift) < 1e-9:
        print(f"OK  sum(buckets) == cumulative (${session_cost:.6f})")
    else:
        print_colored_error(
            f"DRIFT sum(buckets)=${bucket_sum:.6f} vs cumulative=${session_cost:.6f} "
            f"(delta=${drift:.6f}) — some cost grew the cumulative but missed the bucket. "
            "Likely a silent exception in the bucket-update try/except at "
            "token_management.py:255-264."
        )


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
            mapping = getattr(config, "MODEL_MAPPING", {})
            for k, v in mapping.items():
                current = ""
                if config.MODEL == v:
                    current = " (active)"
                print(f"  {k:16} -> {v}{current}")
            print("Use the key (e.g. 'o3') of the model you wish to set as active.")
            return

        model_arg = str(arg).strip()
        ok = config.set_model(model_arg)
        if not ok:
            logger.warning("LLM change request could not be applied: %s", model_arg)
            print_colored_error(f"Could not apply model '{model_arg}'. Active model not changed.")
            return
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
        mapping = getattr(config, "MODEL_MAPPING", {})
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
        # Lazy import to avoid a module-load cycle.
        from monitor.lib.history import adjust_history_size
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
