"""Orchestrator-side singleton: owns the AgentListener and a frame registry.

Implements the orchestrator half of Phase 0.5 (and the seed of Phase 3's
lock-guarded shared state) from docs/cache/PLAN_AGENT_ORCHESTRATION.md.

One listener per orchestrator process. The parent monitor lazily starts it the
first time it spawns a sub-agent (``ensure_started``) and hands the socket path
to children via ``MONITOR_AGENT_SOCKET``. Children (running ``monitor --agent``)
connect with ``agent_reporter`` and stream frames here, where they are recorded
per ``agent_id`` in a thread-safe registry.

This is the PLAN's model: orchestrator = server (listener), child = client
(reporter) — the opposite of the legacy child-served status-socket + poller
approach, which this supersedes.

stdlib + agent_listener/agent_protocol → no monitor.config dependency, so it is
import-cycle-safe and can be imported from screen_handler at spawn time.
"""

from __future__ import annotations

import collections
import logging
import os
import tempfile
import threading
from typing import Any, Deque, Dict, List, Optional

from monitor.lib import agent_protocol as ap
from monitor.lib.agent_listener import AgentListener

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_listener: Optional[AgentListener] = None

# agent_id -> record. Guarded by _registry_lock — this is the lock-guarded
# shared state Phase 3's bridge and Phase 8's gather tool read.
_registry: Dict[str, Dict[str, Any]] = {}
_registry_lock = threading.Lock()

# Bounded buffer of formatted output blocks (stdout/result) awaiting display
# above the next prompt (Phase 3 bridge). Bounded so a chatty agent can't grow
# memory without limit; under overflow the oldest stdout lines drop (results are
# short and rarely lost). Guarded by _registry_lock.
_MAX_PENDING_OUTPUT = 2000
_pending_output: Deque[str] = collections.deque(maxlen=_MAX_PENDING_OUTPUT)


def _default_socket_path() -> str:
    # Short path under the runtime/temp dir (mind the ~104-byte sun_path limit).
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return os.path.join(base, f"m3-orch-{os.getpid()}.sock")


def _blank_record(conn_id: Optional[int] = None) -> Dict[str, Any]:
    return {
        "frames": [],
        "status": None,
        "results": [],
        "error": None,
        "terminal": False,
        "dirty": False,
        "conn_id": conn_id,
    }


def _on_frame(frame: Dict[str, Any], conn_id: int) -> None:
    agent_id = frame.get("agent_id")
    if not agent_id:
        return
    ftype = frame.get("type")
    with _registry_lock:
        rec = _registry.get(agent_id)
        if rec is None:
            rec = _blank_record(conn_id)
            _registry[agent_id] = rec
        rec["conn_id"] = conn_id
        rec["frames"].append(frame)
        if ftype == ap.STATUS:
            rec["status"] = frame["body"].get("label")
        elif ftype == ap.STDOUT:
            chunk = frame["body"].get("chunk", "")
            for line in str(chunk).splitlines() or [""]:
                _pending_output.append(f"[{agent_id}] {line}")
        elif ftype == ap.RESULT:
            rec["results"].append(frame["body"])
            rec["terminal"] = True
            ok = frame["body"].get("ok", True)
            summary = frame["body"].get("summary", "")
            _pending_output.append(f"[{agent_id}] {'✓' if ok else '✗'} {summary}")
        elif ftype == ap.ERROR:
            rec["error"] = frame["body"]
            rec["terminal"] = True
            _pending_output.append(
                f"[{agent_id}] ✗ error: {frame['body'].get('message', '')}"
            )
        elif ftype == ap.EXIT:
            rec["terminal"] = True


def _on_disconnect(conn_id: int, agent_id: Optional[str], dirty: bool) -> None:
    if not agent_id:
        return
    with _registry_lock:
        rec = _registry.get(agent_id)
        if rec is None:
            rec = _blank_record(conn_id)
            _registry[agent_id] = rec
        # Authoritative crash signal: closed without a terminal frame.
        rec["dirty"] = bool(dirty) and not rec["terminal"]


def ensure_started() -> str:
    """Start the listener if needed; return its socket path. Idempotent."""
    global _listener
    with _lock:
        if _listener is None:
            path = _default_socket_path()
            lis = AgentListener(path, on_frame=_on_frame, on_disconnect=_on_disconnect)
            lis.start()
            _listener = lis
            logger.info("Agent orchestrator listener started at %s", path)
        return _listener.socket_path


def socket_path() -> Optional[str]:
    with _lock:
        return _listener.socket_path if _listener is not None else None


def is_running() -> bool:
    with _lock:
        return _listener is not None


# --- read API (used by UI / gather tool) ------------------------------------

def agent_status(agent_id: str) -> Optional[str]:
    with _registry_lock:
        rec = _registry.get(agent_id)
        return rec["status"] if rec else None


def agent_record(agent_id: str) -> Optional[Dict[str, Any]]:
    """A shallow copy of an agent's record (or None)."""
    with _registry_lock:
        rec = _registry.get(agent_id)
        return dict(rec) if rec else None


def all_statuses() -> Dict[str, Optional[str]]:
    """agent_id -> latest status label (snapshot)."""
    with _registry_lock:
        return {aid: rec["status"] for aid, rec in _registry.items()}


def all_agent_ids() -> List[str]:
    with _registry_lock:
        return list(_registry.keys())


# --- bridge: terminal display (Phase 3) -------------------------------------

def drain_pending_output() -> List[str]:
    """Return and clear buffered output blocks (stdout/result) for display."""
    with _registry_lock:
        out = list(_pending_output)
        _pending_output.clear()
        return out


def has_active_agents() -> bool:
    """True if any agent is still running (non-terminal). Gates the toolbar so
    normal (no-agent) prompting is byte-identical."""
    with _registry_lock:
        return any(not rec["terminal"] for rec in _registry.values())


def render_toolbar() -> str:
    """One-line live status of active agents for the prompt_toolkit toolbar.

    Returns "" when no agents are active so the toolbar is hidden in normal use.
    """
    with _registry_lock:
        active = [
            (aid, rec["status"]) for aid, rec in _registry.items() if not rec["terminal"]
        ]
    if not active:
        return ""
    parts = [f"{aid}: {status or '…'}" for aid, status in active]
    return "agents — " + "  ".join(parts)


# --- lifecycle / tests ------------------------------------------------------

def stop() -> None:
    global _listener
    with _lock:
        lis = _listener
        _listener = None
    if lis is not None:
        lis.stop()


def reset_for_test() -> None:
    """Stop the listener and clear the registry (test-only)."""
    stop()
    with _registry_lock:
        _registry.clear()
        _pending_output.clear()
