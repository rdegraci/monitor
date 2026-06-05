"""Utility helpers extracted from terminal_commands.py.

This module contains pure helper functions that do not depend on the
module-level ScreenHandler state. They were moved here to keep
terminal_commands.py focused on screen-related behavior and to reduce
file size.

Historical note: this module also used to hold an orchestrator-poller
registry (register_orchestrator_entry / remove_orchestrator_entries_by_target,
backed by an in-memory _ORCH_ENTRIES map). That was part of the legacy
child-served status-socket + poller model, which the frame-protocol
orchestrator (monitor.lib.agent_orchestrator / agent_listener) replaced. The
registry's only producer (the :agent spawn fallthrough) was removed, leaving
it dead, so the whole registry was deleted during the orchestration cleanup.
"""

import logging
import platform
import shutil

# Set up a module-level logger
logger = logging.getLogger(__name__)


def _color(text, color):
    """Return text wrapped in ANSI color codes.

    Args:
        text (str): Text to colorize.
        color (str): One of "green", "yellow", "red", "blue", "magenta", "reset".

    Returns:
        str: Colorized text using ANSI escape sequences if supported.
    """
    colors = {
        "reset": "\033[0m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
    }
    prefix = colors.get(color, "")
    suffix = colors.get("reset", "")
    if not prefix:
        return text
    return f"{prefix}{text}{suffix}"


def user_feedback(message):
    """UX helper for user-facing feedback; currently logs as INFO.

    Args:
        message (str): The message to deliver to the user.
    """
    logger.info(message)


def is_executable_on_path(executable):
    """Check if an executable exists on the current system PATH.

    Args:
        executable (str): The executable name to check.

    Returns:
        bool: True if found, False otherwise.
    """
    return shutil.which(executable) is not None


def is_platform_mac():
    """Check if the current platform is macOS.

    Returns:
        bool: True if running on macOS, False otherwise.
    """
    return platform.system() == "Darwin"


def is_platform_unix():
    """Check if the current platform is UNIX-like (Linux or Darwin).

    Returns:
        bool: True if running on a UNIX-like system, False otherwise.
    """
    return platform.system() in ("Linux", "Darwin")
