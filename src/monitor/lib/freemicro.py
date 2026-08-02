"""Best-effort FreeMicro Agent Key hooks for the Codex Micro pad.

When enabled, Monitor emits Claude-shaped lifecycle JSON to ``freemicro hook``
so a FreeMicro daemon can light Agent Keys and focus this session's terminal.

Off by default. Enable with ``FREEMICRO_HOOKS: true`` in config.yaml or
``MONITOR_FREEMICRO_HOOKS=1`` in the environment. Requires ``freemicro`` on
``PATH`` and a running FreeMicro ``run``/daemon with lights enabled.

Never raises into the REPL. A missing binary, slow hook, or pad outage must
not break a turn.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import shutil
import subprocess
from typing import Any, Optional

from monitor import config

logger = logging.getLogger(__name__)

#: Max seconds to wait for ``freemicro hook``. Hooks must stay snappy.
_HOOK_TIMEOUT = 2.0

_started = False
_atexit_registered = False
_binary_cache: Optional[str] = None


def enabled() -> bool:
    """True when FreeMicro hooks are turned on for this process."""
    return bool(getattr(config, "FREEMICRO_HOOKS", False))


def _binary() -> Optional[str]:
    """Resolve ``freemicro`` once; None if not on PATH."""
    global _binary_cache
    if _binary_cache is not None:
        return _binary_cache or None
    path = shutil.which("freemicro")
    _binary_cache = path or ""
    return path


def _session_id() -> str:
    return str(getattr(config, "SESSION_ID", None) or "monitor")


def _cwd() -> str:
    try:
        return os.getcwd()
    except OSError:
        return ""


def emit(hook_event_name: str, **extra: Any) -> None:
    """Send one Claude-shaped hook event to FreeMicro. Never raises."""
    if not enabled():
        return
    binary = _binary()
    if not binary:
        logger.debug("freemicro not on PATH; skipping %s", hook_event_name)
        return
    payload: dict[str, Any] = {
        "hook_event_name": hook_event_name,
        "session_id": _session_id(),
        "cwd": _cwd(),
        "title": "monitor",
        # Long-lived Monitor pid so FreeMicro stores this tab for focus /
        # liveness, not the short-lived ``freemicro hook`` child.
        "pid": os.getpid(),
    }
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    try:
        subprocess.run(
            [binary, "hook"],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            timeout=_HOOK_TIMEOUT,
            check=False,
        )
    except Exception:
        logger.debug("freemicro hook %s failed", hook_event_name, exc_info=True)


def ensure_session() -> None:
    """Emit ``SessionStart`` once per process when hooks are enabled."""
    global _started, _atexit_registered
    if not enabled() or _started:
        return
    _started = True
    emit("SessionStart")
    if not _atexit_registered:
        atexit.register(session_end)
        _atexit_registered = True


def session_start() -> None:
    """Register this Monitor process on an Agent Key (idle)."""
    ensure_session()


def prompt_submit() -> None:
    """User submitted a prompt; pad goes working (blue)."""
    ensure_session()
    emit("UserPromptSubmit")


def pre_tool_use(tool_name: Optional[str] = None) -> None:
    """A tool is about to run; keep the key working."""
    ensure_session()
    emit("PreToolUse", tool_name=tool_name)


def post_tool_use(tool_name: Optional[str] = None) -> None:
    """A tool finished; still working until the turn stops."""
    emit("PostToolUse", tool_name=tool_name)


def stop(*, error: bool = False) -> None:
    """Turn finished: green done, or red error."""
    if error:
        emit("Stop", is_error=True)
    else:
        emit("Stop")


def session_end(*, reason: str = "exit") -> None:
    """Session closed; FreeMicro clears the session record."""
    global _started
    if not _started and not enabled():
        return
    emit("SessionEnd", reason=reason)
    _started = False
