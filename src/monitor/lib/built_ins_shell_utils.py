"""Shell-oriented helper utilities for built-in commands."""

import logging
import os
from typing import Any

from monitor.lib.bm25 import clear_bm25_cache

logger = logging.getLogger(__name__)


def handle_cd_command(args: str) -> str:
    """Change the current working directory.

    Args:
        args: Path to the target directory.

    Returns:
        The new working directory on success, or an error message on failure.
    """
    try:
        os.chdir(os.path.expanduser(args))
        clear_bm25_cache()
        cwd = os.getcwd()
        return cwd
    except FileNotFoundError:
        logger.error("Directory not found: %s", args)
        return f"Directory not found: {args}"
    except NotADirectoryError:
        logger.error("Not a directory: %s", args)
        return f"Not a directory: {args}"
    except PermissionError:
        logger.error("Permission denied: %s", args)
        return f"Permission denied: {args}"


def clear_screen() -> None:
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def print_debug(command_to_run: Any, debug: bool = True) -> None:
    """Print debug information when debug mode is enabled.

    Args:
        command_to_run: The object or command to log.
        debug: Whether debug logging is enabled for this call.
    """
    if debug:
        logger.debug(command_to_run)
