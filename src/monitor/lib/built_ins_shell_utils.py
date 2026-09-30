"""Shell-oriented helper utilities for built-in commands."""

import logging
import os
import shlex
import tempfile
from typing import Any

from monitor.lib.bm25 import clear_bm25_cache

logger = logging.getLogger(__name__)

# Marker prepended to the interactive zsh PROMPT when `shell` is launched from
# Monitor. Kept as a constant so tests and the wrapper rc stay in sync.
MONITOR_SHELL_PROMPT_PREFIX = "[Monitor] "


def _monitor_shell_zshrc_body() -> str:
    """Return the session-local ``.zshrc`` that prefixes PROMPT with ``[Monitor]``."""
    prefix = MONITOR_SHELL_PROMPT_PREFIX
    return f"""\
# Monitor-managed interactive shell wrapper (session-local; do not edit).
# Source the user's normal zshrc, then keep a [Monitor] prefix on PROMPT.
if [ -n "${{MONITOR_USER_ZDOTDIR}}" ] && [ -f "${{MONITOR_USER_ZDOTDIR}}/.zshrc" ]; then
  . "${{MONITOR_USER_ZDOTDIR}}/.zshrc"
elif [ -f "${{HOME}}/.zshrc" ]; then
  . "${{HOME}}/.zshrc"
fi
_monitor_prompt_prefix() {{
  case "$PROMPT" in
    '[Monitor]'*) ;;
    *) PROMPT="{prefix}$PROMPT" ;;
  esac
}}
autoload -Uz add-zsh-hook 2>/dev/null && add-zsh-hook precmd _monitor_prompt_prefix
_monitor_prompt_prefix
"""


def prepare_monitor_shell_zdotdir() -> str:
    """Create a temporary ZDOTDIR that prefixes PROMPT with ``[Monitor]``.

    The wrapper ``.zshrc`` sources the user's real rc (via ``MONITOR_USER_ZDOTDIR``
    or ``$HOME/.zshrc``), then installs a precmd hook so themes that rebuild
    PROMPT each redraw still keep the prefix.

    Returns:
        Path to the temporary ZDOTDIR. Caller must remove it when the shell exits.
    """
    tmp = tempfile.mkdtemp(prefix="monitor-shell-")
    zshrc_path = os.path.join(tmp, ".zshrc")
    with open(zshrc_path, "w", encoding="utf-8") as fh:
        fh.write(_monitor_shell_zshrc_body())
    logger.debug("Prepared Monitor shell ZDOTDIR at %s", tmp)
    return tmp


def build_monitor_shell_command(extra_args: str = "") -> tuple[str, str]:
    """Build the subprocess command string for Monitor's interactive ``shell``.

    Args:
        extra_args: Optional arguments appended after ``zsh`` (already shell-safe
            or raw remainder as chosen by the caller).

    Returns:
        ``(command_string, zdotdir_path)``. Run ``command_string`` then remove
        ``zdotdir_path``.
    """
    zdotdir = prepare_monitor_shell_zdotdir()
    user_zdot = os.environ.get("ZDOTDIR", "")
    parts = [
        f"MONITOR_USER_ZDOTDIR={shlex.quote(user_zdot)}",
        f"ZDOTDIR={shlex.quote(zdotdir)}",
        "zsh",
    ]
    if extra_args:
        parts.append(extra_args)
    return " ".join(parts), zdotdir


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
