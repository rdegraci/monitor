"""Utilities for ScreenHandler.

This module collects small helper routines used by monitor.lib.screen_handler.
These functions are kept independent so they can be tested separately and to
reduce noise in the main ScreenHandler implementation.
"""

from __future__ import annotations

import logging
import subprocess
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def shutil_which(exe: str) -> Optional[str]:
    """Return the path to an executable or None if not found.

    This is a thin wrapper around shutil.which kept local to avoid importing
    shutil at module import time in calling modules during tests.

    Args:
        exe: Executable name to locate.

    Returns:
        The path to the executable or None if not found.
    """
    try:
        import shutil

        return shutil.which(exe)
    except Exception:
        return None


def parse_screen_ls_tokens(output: str) -> List[str]:
    """Parse the output of `screen -ls` and return tokens of form '<pid>.<name>'.

    Only tokens whose left-hand side is an integer pid are returned.

    Args:
        output: The full stdout text from `screen -ls`.

    Returns:
        A list of token strings like '1234.mysession'.
    """
    tokens: List[str] = []
    if not output:
        return tokens
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        for p in parts:
            if "." in p:
                pid_part = p.split(".", 1)[0]
                if pid_part.isdigit():
                    tokens.append(p)
    return tokens


def resolve_screen_token(screen_cmd: str, session_name: str) -> Optional[str]:
    """Resolve the preferred screen token for a given session name.

    Runs `screen -ls` and selects the candidate token ending with
    '.{session_name}' that has the highest PID. If no candidate is found
    or listing fails, None is returned.

    Args:
        screen_cmd: The screen executable to invoke.
        session_name: The session name to resolve.

    Returns:
        The resolved token string (e.g. '1234.mysession') or None.
    """
    try:
        ls = subprocess.run([screen_cmd, "-ls"], capture_output=True, text=True)
        out = ls.stdout or ""
        candidates: List[Tuple[int, str]] = []
        for token in parse_screen_ls_tokens(out):
            if token.endswith(f".{session_name}"):
                pid_part = token.split(".", 1)[0]
                try:
                    pid_val = int(pid_part)
                except Exception:
                    pid_val = -1
                candidates.append((pid_val, token))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
        return None
    except Exception:
        logger.exception("Failed to run '%s -ls' when resolving token for %s", screen_cmd, session_name)
        return None


def find_tokens_for_name(screen_cmd: str, session_name: str) -> List[str]:
    """Return all tokens from `screen -ls` that end with '.{session_name}'.

    Only tokens whose left-hand side is numeric are included.

    Args:
        screen_cmd: The screen executable to invoke.
        session_name: The session name to find tokens for.

    Returns:
        A list of token strings.
    """
    try:
        ls = subprocess.run([screen_cmd, "-ls"], capture_output=True, text=True)
        out = ls.stdout or ""
        matches: List[str] = []
        for token in parse_screen_ls_tokens(out):
            if token.endswith(f".{session_name}"):
                matches.append(token)
        return matches
    except Exception:
        logger.exception("Failed to list screen sessions when finding tokens for %s", session_name)
        return []
