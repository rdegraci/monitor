"""Helpers for writing per-subagent JSONL logs when agent flag is enabled."""

from __future__ import annotations

import json
import os
import errno
from pathlib import Path
from typing import Optional
import appdirs
import logging

logger = logging.getLogger(__name__)


def _ensure_dir(path: Path) -> None:
    """Ensure directory exists with restrictive permissions.

    Args:
        path: Directory path to create.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path, 0o700)
        except Exception:
            # Not fatal if chmod unsupported
            pass
    except Exception:
        logger.exception("Failed to create subagent log directory: %s", str(path))


def _atomic_append(path: Path, line: str) -> None:
    """Atomically append a line to a file and fsync.

    Uses os.open with O_APPEND to avoid races between processes.

    Args:
        path: File path to append to.
        line: Line content (should include trailing newline).
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    mode = 0o600
    fd = None
    try:
        fd = os.open(str(path), flags, mode)
        os.write(fd, line.encode("utf-8"))
        try:
            os.fsync(fd)
        except Exception:
            # Not fatal
            pass
    except Exception:
        logger.exception("Failed to append to subagent log %s", str(path))
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass


def _find_meta_for_socket(socket_path: str) -> Optional[Path]:
    """Search user data subagents metadata dir for a JSON file with matching socket_path.

    Args:
        socket_path: Socket path to match against metadata entries.

    Returns:
        Path to metadata JSON if found, otherwise None.
    """
    base = Path(appdirs.user_data_dir("monitor")) / "subagents"
    if not base.exists():
        return None
    try:
        for p in base.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict) and data.get("socket_path") == socket_path:
                    return p
            except Exception:
                continue
    except Exception:
        logger.exception("Failed searching for metadata files in %s", str(base))
    return None


def append_interaction(prompt_text: str, reply_text: str, explicit_path: Optional[str] = None) -> None:
    """Append a minimal JSONL interaction record to the per-session subagent log.

    The record is a single JSON object per line with two keys: prompt_text and reply_text.
    If explicit_path is provided, it is used as the target file path. Otherwise the function
    attempts to locate the session metadata by matching MONITOR_STATUS_SOCKET environment
    variable to a metadata file and reading its 'log_path'. If that fails, a default file is
    created under the user cache subagents directory named by date.

    Args:
        prompt_text: The user prompt string.
        reply_text: The reply produced by the agent/LLM.
        explicit_path: Optional explicit path to the logfile to append to.
    """
    try:
        # If caller provided explicit path, prefer it
        if explicit_path:
            target = Path(explicit_path)
        else:
            # Try to resolve via status socket meta link
            sock = os.environ.get("MONITOR_STATUS_SOCKET")
            if sock:
                meta = _find_meta_for_socket(sock)
                if meta:
                    try:
                        with open(meta, "r", encoding="utf-8") as fh:
                            data = json.load(fh)
                        lp = data.get("log_path")
                        if lp:
                            target = Path(lp)
                        else:
                            target = None
                    except Exception:
                        target = None
                else:
                    target = None
            else:
                target = None
        # Fallback to default cache dir
        if not target:
            base = Path(appdirs.user_cache_dir("monitor")) / "subagents"
            _ensure_dir(base)
            # Use a date-based filename to group by day
            name = f"{Path(os.getlogin()).stem}_{os.getpid()}_{Path(os.getcwd()).name}.log"
            target = base / name
        # Ensure parent dir exists
        _ensure_dir(target.parent)
        record = {"prompt_text": prompt_text, "reply_text": reply_text}
        line = json.dumps(record, ensure_ascii=False) + "\n"
        _atomic_append(target, line)
    except Exception:
        logger.exception("Unhandled error while appending subagent interaction")
