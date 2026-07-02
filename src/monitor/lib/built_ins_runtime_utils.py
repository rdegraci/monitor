"""Runtime configuration command helpers for built-in command dispatch."""

import json
import logging
from typing import Any

from monitor import config as runtime_config
from monitor.lib.colors import print_yellow
from monitor.lib.display_output import print_colored_error

logger = logging.getLogger(__name__)

config = runtime_config

_SETTINGS_EXCLUDED_KEYS = {
    "CONVERSATION_HISTORY",
    "FUNCTION_KEY_INSERTIONS",
    "PROJECT_INSTRUCTIONS_CONTENT",
    "_MODEL_CONFIG_CACHE",
    "_VALID_REASONING_EFFORTS",
}


def _active_config():
    """Return the currently active config module for runtime commands.

    Returns:
        The config object, preferring the built_in_commands re-export when
        available so legacy tests that patch that path keep working.
    """
    try:
        from monitor.lib import built_in_commands

        return getattr(built_in_commands, "config", config)
    except Exception:
        return config

def _make_json_safe(value: Any) -> Any:
    """Convert runtime config values into JSON-safe structures.

    Args:
        value: Arbitrary runtime configuration value.

    Returns:
        A value composed only of JSON-safe container/value types. Non-serializable
        objects are converted to ``repr(value)``. Dictionary keys are coerced to
        strings so nested mixed-type mappings remain sortable.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _make_json_safe(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_make_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(repr(item) for item in value)
    return repr(value)


def settings_command(arg: str | None = None) -> None:
    """Dump the live runtime configuration settings as formatted JSON.

    Args:
        arg: Optional selector. Pass ``help`` to show usage. Pass a non-empty
            value other than help to filter to config attributes containing the
            supplied substring (case-insensitive).

    Returns:
        None.
    """
    active_config = _active_config()
    arg_text = "" if arg is None else str(arg).strip()
    if arg_text.lower() in {"help", "?", "-h", "--help"}:
        print("Dump live runtime configuration settings as JSON.")
        print("Usage: : (or /) settings [substring_filter]")
        print("Examples:")
        print("  :settings")
        print("  :settings model")
        return

    filter_text = arg_text.lower()
    settings_payload: dict[str, Any] = {}
    for name in sorted(dir(active_config)):
        if name in _SETTINGS_EXCLUDED_KEYS:
            continue
        if not name.isupper() and name not in _SETTINGS_EXCLUDED_KEYS:
            continue
        if filter_text and filter_text not in name.lower():
            continue
        try:
            value = getattr(active_config, name)
        except Exception as exc:
            settings_payload[name] = f"<unavailable: {exc}>"
            continue
        settings_payload[name] = _make_json_safe(value)

    print(json.dumps(settings_payload, indent=2, sort_keys=True))



def reasoning_command(arg: str | None = None) -> None:
    """Change the reasoning effort level at runtime.

    Usage:
        :reasoning <minimal|low|medium|high|xhigh>

    With no argument or ``help``, prints available options, current setting,
    and the reasoning model prefix requirement.

    Args:
        arg: Optional reasoning effort override.

    Returns:
        None.
    """
    try:
        active_config = _active_config()
        arg_provided = arg is not None and str(arg).strip() != ""
        if not arg_provided or str(arg).strip().lower() in {"help", "?", "-h", "--help"}:
            current = getattr(active_config, "REASONING_EFFORT", None)
            prefix = getattr(active_config, "REASONING_MODEL_PREFIX", "")
            print("Set the reasoning effort level used with reasoning-capable models.")
            print("Usage: : (or /) reasoning <minimal|low|medium|high|xhigh>")
            print(f"Current reasoning effort: {current}")
            print(f"Reasoning model prefix requirement: {prefix}")
            return

        value = str(arg).strip().lower()
        valid = {"minimal", "low", "medium", "high", "xhigh"}
        if value not in valid:
            print_colored_error(
                "Invalid reasoning effort. Valid options: minimal, low, medium, high, xhigh."
            )
            return

        active_config.REASONING_EFFORT = value
        prefix = getattr(active_config, "REASONING_MODEL_PREFIX", "")
        print_yellow(
            f"Reasoning effort set to: {active_config.REASONING_EFFORT}\n"
            f"Reasoning model prefix requirement: {prefix}\n"
            f"Active model: {active_config.MODEL}"
        )
        try:
            model_name = str(getattr(active_config, "MODEL", ""))
            prefix_str = "" if prefix is None else str(prefix)
            if prefix_str and prefix_str.lower() not in model_name.lower():
                print_yellow(
                    "Warning: Active model does not match the reasoning model "
                    "prefix; the reasoning effort setting may have no effect."
                )
        except Exception:
            pass
    except Exception as exc:
        print_colored_error(f"Could not set reasoning effort: {exc}")


def _ttl_minutes_from_api_value(api_value: str) -> int:
    """Convert an Anthropic cache TTL string to display minutes.

    Args:
        api_value: Anthropic ``cache_control.ttl`` string.

    Returns:
        Integer minute count for display.
    """
    if api_value == "5m":
        return 5
    return 60


def _print_ttl_help(current_minutes: int) -> None:
    """Print help text for the ``:ttl`` command.

    Args:
        current_minutes: Current TTL in minutes.

    Returns:
        None.
    """
    print("Set the Anthropic prompt-cache TTL for the system + tools breakpoints.")
    print("Usage: : (or /) ttl <minutes>")
    print("Valid values:")
    print("  :ttl 5 or /ttl 5    — 5-minute cache (write at 1.25x base input cost)")
    print(
        "  :ttl 60 or /ttl 60   — 1-hour cache (write at 2x base input cost; "
        "wins when idle >5min)"
    )
    print("Reads cost 0.1x base for both TTLs. The final-user-message breakpoint")
    print("stays at 5m regardless (it changes every turn).")
    print(f"Current TTL: {current_minutes} minutes.")


def ttl_command(arg: str | None = None) -> None:
    """Configure the Anthropic prompt-cache TTL at runtime.

    Args:
        arg: Optional string minute value.

    Returns:
        None.
    """
    active_config = _active_config()
    current_api = getattr(active_config, "ANTHROPIC_CACHE_TTL", "1h")
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
        active_config.ANTHROPIC_CACHE_TTL = "5m"
        print_yellow(
            "Anthropic prompt-cache TTL set to 5 minutes (system + tools breakpoints)."
        )
    elif minutes == 60:
        active_config.ANTHROPIC_CACHE_TTL = "1h"
        print_yellow(
            "Anthropic prompt-cache TTL set to 1 hour (system + tools breakpoints)."
        )
    else:
        print_colored_error(
            f"Invalid value: {minutes}. Anthropic supports only 5 or 60 minutes."
        )
        _print_ttl_help(current_minutes)


def _print_max_tokens_help(current_value: int) -> None:
    """Print help text for the ``:max_tokens`` command.

    Args:
        current_value: Current output-token cap.

    Returns:
        None.
    """
    print("Cap output tokens for non-reasoning model calls (max_completion_tokens).")
    print("Usage: : (or /) max_tokens <N>")
    print(
        "Reasoning models (gpt-5-style) use REASONING_MAX_COMPLETION_TOKENS "
        "instead;"
    )
    print("this cap does not affect them. Raise the value for long-form generation,")
    print("lower it to cut runaway tail-end completions.")
    print(f"Current cap: {current_value} tokens.")


def max_tokens_command(arg: str | None = None) -> None:
    """Configure the non-reasoning output-token cap at runtime.

    Args:
        arg: Optional positive integer string.

    Returns:
        None.
    """
    active_config = _active_config()
    current = getattr(active_config, "MAX_COMPLETION_TOKENS", 8192)

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

    active_config.MAX_COMPLETION_TOKENS = new_cap
    print_yellow(f"Output-token cap set to {new_cap} (non-reasoning model calls).")


def llm_command(arg: str | None = None) -> None:
    """Change the active LLM model at runtime.

    Args:
        arg: Model shorthand, full model name, or help token.

    Returns:
        None.
    """
    try:
        active_config = _active_config()
        arg_provided = arg is not None and str(arg).strip() != ""
        if not arg_provided or str(arg).strip().lower() in {"help", "?", "-h", "--help"}:
            print("Dynamically set the active LLM model for completions.")
            print("Usage: : (or /) llm <modelname>")
            print("Available models:")
            mapping = getattr(active_config, "MODEL_MAPPING", {})
            for key, value in mapping.items():
                current = ""
                if active_config.MODEL == value:
                    current = " (active)"
                print(f"  {key:16} -> {value}{current}")
            print("Use the key (e.g. 'o3') of the model you wish to set as active.")
            return

        model_arg = str(arg).strip()
        ok = active_config.set_model(model_arg)
        if not ok:
            logger.warning("LLM change request could not be applied: %s", model_arg)
            print_colored_error(
                f"Could not apply model '{model_arg}'. Active model not changed."
            )
            return
        active_config.configure_subsystems()
        print_yellow(
            f"Active model set to: {active_config.MODEL}\n"
            f"MODEL_CONTEXT_WINDOW = {active_config.MODEL_CONTEXT_WINDOW}\n"
            f"MODEL_OUTPUT_WINDOW = {active_config.MODEL_OUTPUT_WINDOW}\n"
            f"MODEL_INPUT_WINDOW = {active_config.MODEL_INPUT_WINDOW}\n"
            f"MODEL_MAX_TPM = {active_config.MODEL_MAX_TPM}\n"
            f"CONVERSATION_MAX_SIZE = {active_config.CONVERSATION_MAX_SIZE}"
        )
    except Exception as exc:
        print_colored_error(f"Could not set LLM model: {exc}")
        active_config = _active_config()
        mapping = getattr(active_config, "MODEL_MAPPING", {})
        if mapping:
            print("Available models:")
            for key, value in mapping.items():
                print(f"  {key:16} -> {value}")
        print("Usage: : (or /) llm <modelname>. See ':llm help' or '/llm help'.")
