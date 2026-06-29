"""Editor and configuration UI helper commands for built-in command dispatch."""

import copy
import logging
import os
import subprocess
from typing import Any

from monitor._stubs import appdirs

from monitor import config
from monitor.function_keys_loader import load_function_keys_config
from monitor.lib.display_output import print_colored_error
from monitor.lib.keyboard import configure_function_key_insertions
from monitor.lib.preferences import open_preferences_editor

logger = logging.getLogger(__name__)


def open_preferences_command(arg: Any | None = None) -> None:
    """Open the preferences prompt file in the configured editor.

    Args:
        arg: Ignored dispatcher argument.

    Returns:
        None.
    """
    del arg
    result = open_preferences_editor(config.PREFERENCE_PROMPT_FILE)
    print(result)


def edit_macros_command(arg: Any | None = None) -> None:
    """Open the macros editor, ignoring any dispatcher argument.

    Args:
        arg: Ignored dispatcher argument.

    Returns:
        None.
    """
    del arg
    from monitor.lib.macros import open_macros_editor

    result = open_macros_editor()
    if result:
        print(result)


def open_function_keys_editor(path: str | None = None) -> str | None:
    """Open the function keys configuration file in a text editor.

    Args:
        path: Optional path to the function keys configuration file.

    Returns:
        The path to the configuration file on success, or ``None`` on failure.
    """
    try:
        if path is None:
            path = os.path.join(
                appdirs.user_config_dir("monitor"),
                "function_keys.json",
            )

        os.makedirs(os.path.dirname(path), exist_ok=True)

        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as file_handle:
                file_handle.write("{}\n")

        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
        result = subprocess.run([editor, path], check=False)
        if result.returncode != 0:
            message = (
                f"Editor exited with non-zero status {result.returncode}: {editor}"
            )
            print_colored_error(message)
            logger.error(message)
            return None
        return path
    except Exception as exc:
        print_colored_error(f"Failed to open function keys editor: {exc}")
        logger.error("Failed to open function keys editor: %s", exc, exc_info=True)
        return None


def edit_function_keys_command(arg: Any | None = None) -> str | None:
    """Edit grouped function key bindings and apply them after saving.

    Args:
        arg: Optional dispatcher argument. If it is a non-empty string, it is
            treated as the configuration file path.

    Returns:
        The path to the configuration file on success, or ``None`` on failure.
    """
    try:
        path = str(arg).strip() if isinstance(arg, str) and str(arg).strip() else None
        config_path = open_function_keys_editor(path)
        if not config_path:
            return None

        grouped_bindings = load_function_keys_config(config_path)
        configure_function_key_insertions(grouped_bindings)
        logger.info("Applied grouped function key bindings from %s", config_path)
        print(f"Function keys configuration updated and applied: {config_path}")
        return config_path
    except Exception as exc:
        print_colored_error(f"Failed to edit function keys configuration: {exc}")
        logger.error(
            "Failed to edit function keys configuration: %s",
            exc,
            exc_info=True,
        )
        return None


def reload_macros_command(arg: Any | None = None) -> None:
    """Reload macros from configuration and print a summary of changes.

    Args:
        arg: Ignored dispatcher argument.

    Returns:
        None.
    """
    del arg
    from monitor.lib.macros import MACRO_VALUES, configure_macros

    try:
        try:
            old_macros = copy.deepcopy(MACRO_VALUES)
        except Exception:
            old_macros = dict(MACRO_VALUES)

        configure_macros()

        try:
            new_macros = copy.deepcopy(MACRO_VALUES)
        except Exception:
            new_macros = dict(MACRO_VALUES)

        old_keys = set(old_macros.keys())
        new_keys = set(new_macros.keys())
        added = sorted(new_keys - old_keys)
        removed = sorted(old_keys - new_keys)
        changed = sorted(
            [key for key in old_keys & new_keys if old_macros[key] != new_macros[key]]
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
    except Exception as exc:
        print_colored_error(f"Failed to reload macros: {exc}")
        logger.error("Failed to reload macros: %s", exc, exc_info=True)
