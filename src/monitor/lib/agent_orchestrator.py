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
import time
from typing import Any, Deque, Dict, List, Optional, Tuple

from monitor.lib import agent_protocol as ap
from monitor.lib.agent_listener import AgentListener

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_listener: Optional[AgentListener] = None

# Spawn accounting for breadth/total caps (Phase 8c). Guarded by _registry_lock.
# active = _total_spawned - _total_resolved counts in-flight agents (spawned but
# not yet finished/crashed) — including ones that haven't connected yet — so a
# rapid fan-out is bounded, not just connected agents.
_total_spawned = 0
_total_resolved = 0

# Heartbeat-lapse detection (Phase 5): an agent that stops sending frames for
# longer than this (hung, or spawned-but-never-connected) is marked dirty so
# agent_gather reports it as failed instead of waiting forever. Reaping a stale
# agent also releases its spawn reservation so the cap can't leak.
def _hb_timeout() -> float:
    # env overrides config.yaml (loaded into config.MONITOR_AGENT_HEARTBEAT_TIMEOUT);
    # both fall back to the safe default. config imported lazily (no cycle).
    val = os.environ.get("MONITOR_AGENT_HEARTBEAT_TIMEOUT")
    if val is None:
        try:
            from monitor import config
            val = getattr(config, "MONITOR_AGENT_HEARTBEAT_TIMEOUT", None)
        except Exception:
            val = None
    if val is None:
        return 45.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 45.0

def _idle_timeout() -> float:
    """Seconds a PERSISTENT sub-agent may sit idle (alive but doing no work,
    only heartbeating) after reporting a result before the idle-reaper kills it
    (PLAN 8f safety net). env overrides config; both fall back to the default."""
    val = os.environ.get("MONITOR_AGENT_IDLE_TIMEOUT")
    if val is None:
        try:
            from monitor import config
            val = getattr(config, "MONITOR_AGENT_IDLE_TIMEOUT", None)
        except Exception:
            val = None
    if val is None:
        return 300.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 300.0

_hb_thread: Optional[threading.Thread] = None
_hb_stop = threading.Event()

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

# Bounded history of recent terminal outcomes so the primary orchestrator can
# show a compact "what just happened" summary without replaying full logs.
_MAX_RECENT_EVENTS = 8
_recent_terminal_events: Deque[Dict[str, str]] = collections.deque(
    maxlen=_MAX_RECENT_EVENTS
)

# Async result harvest (Phase 8a): when a background sub-agent reaches a terminal
# state, a one-line notice is queued here (guarded by _registry_lock, written
# from reader/heartbeat threads). The MAIN thread drains it at query-prep time
# and feeds it to config.enqueue_next_llm_prefix — so config's prefix list is
# only ever mutated on the main thread (no cross-thread race with its iterate+
# clear). Each agent is injected at most once (the record's "_injected" flag).
_pending_injections: List[str] = []
_INJECTION_SUMMARY_CAP = 4000  # truncate a huge subagent summary before injecting

# Sub-agent cost telemetry (Stage 2): sanitized `usage` blocks from `result`
# frames, awaiting fold into the orchestrator's session totals. Accumulated by
# the reader thread (under _registry_lock) and drained on the MAIN thread, so
# config cost globals are never mutated cross-thread.
_pending_usage: List[Dict[str, Any]] = []


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
        "persistent": False,
        "followup_pending": False,
        "last_followup_sent_at": None,
        "conn_id": conn_id,
        "last_frame": time.monotonic(),
        "last_activity": time.monotonic(),  # last NON-heartbeat frame (real work)
        "_resolved_counted": False,
        "_injected": False,
        "_reaped": False,
    }


def _count_resolved(rec: Dict[str, Any]) -> None:
    """Mark a record as resolved (finished/crashed) exactly once, for caps.
    Must be called while holding _registry_lock."""
    global _total_resolved
    if not rec.get("_resolved_counted"):
        rec["_resolved_counted"] = True
        _total_resolved += 1


def _queue_injection(agent_id: str, rec: Dict[str, Any], text: str) -> None:
    """Queue a one-line completion notice for the orchestrator's next turn,
    at most once per agent. Must be called while holding _registry_lock."""
    if rec.get("_injected"):
        return
    rec["_injected"] = True
    _pending_injections.append(text)


def _push_terminal_event(agent_id: str, outcome: str, summary: str) -> None:
    """Record a compact terminal outcome for operator-facing visibility."""
    text = " ".join(str(summary or "").split()).strip()
    if not text:
        text = "completed" if outcome == "ok" else "failed"
    _recent_terminal_events.append(
        {"agent_id": str(agent_id), "outcome": str(outcome), "summary": text}
    )


def _classify_record(rec: Dict[str, Any]) -> str:
    """Return one of running/completed/failed for a registry record."""
    if rec.get("dirty") or rec.get("error"):
        return "failed"
    if rec.get("followup_pending"):
        return "running"
    results = rec.get("results") or []
    if results:
        return "completed" if results[-1].get("ok", True) else "failed"
    if rec.get("terminal"):
        return "completed"
    return "running"


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
        rec["last_frame"] = time.monotonic()
        # last_activity tracks real work (everything except heartbeats), so the
        # idle-reaper can tell an idle-but-alive agent from a busy one.
        if ftype != ap.HEARTBEAT:
            rec["last_activity"] = rec["last_frame"]
            rec["followup_pending"] = False
        if ftype in (ap.STATUS, ap.STDOUT) and rec.get("terminal"):
            rec["terminal"] = False
            rec["_reaped"] = False
            rec["error"] = None
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
            _count_resolved(rec)
            # Cost telemetry: queue the sanitized usage delta for the main thread
            # to fold into session totals (best-effort; absent/bad usage ignored).
            usage = ap.sanitize_usage(frame["body"].get("usage"))
            if usage is not None:
                _pending_usage.append(usage)
            ok = frame["body"].get("ok", True)
            summary = frame["body"].get("summary", "")
            _push_terminal_event(agent_id, "ok" if ok else "failed", summary)
            _pending_output.append(f"[{agent_id}] {'✓' if ok else '✗'} {summary}")
            verb = "finished" if ok else "FAILED"
            _queue_injection(
                agent_id, rec,
                f"Background sub-agent '{agent_id}' {verb}: {summary[:_INJECTION_SUMMARY_CAP]}",
            )
        elif ftype == ap.ERROR:
            rec["error"] = frame["body"]
            rec["terminal"] = True
            _count_resolved(rec)
            msg = frame["body"].get("message", "")
            _push_terminal_event(agent_id, "failed", msg)
            _pending_output.append(f"[{agent_id}] ✗ error: {msg}")
            _queue_injection(
                agent_id, rec,
                f"Background sub-agent '{agent_id}' FAILED: {msg[:_INJECTION_SUMMARY_CAP]}",
            )
        elif ftype == ap.EXIT:
            rec["terminal"] = True
            _count_resolved(rec)


def _on_disconnect(conn_id: int, agent_id: Optional[str], dirty: bool) -> None:
    if not agent_id:
        return
    with _registry_lock:
        rec = _registry.get(agent_id)
        if rec is None:
            rec = _blank_record(conn_id)
            _registry[agent_id] = rec
        # Authoritative crash signal: closed without a terminal frame.
        if bool(dirty) and not rec["terminal"]:
            rec["dirty"] = True
            _count_resolved(rec)
            _push_terminal_event(
                agent_id, "failed", "crashed (disconnected before reporting a result)"
            )
            _queue_injection(
                agent_id, rec,
                f"Background sub-agent '{agent_id}' FAILED: crashed (disconnected "
                f"before reporting a result).",
            )
        elif rec["terminal"]:
            # Clean close after a terminal frame — already counted.
            _count_resolved(rec)


def _kill_session(agent_id: str) -> None:
    """Best-effort kill of a sub-agent's screen session (agent_id == session
    name). Lazy import keeps agent_orchestrator free of a screen_handler import
    at module load; failures are swallowed (best-effort reaping)."""
    try:
        from monitor.lib.screen_handler import get_global_screen_handler
        get_global_screen_handler().kill_session(agent_id)
    except Exception:
        logger.debug("idle-reap: could not kill session %s", agent_id, exc_info=True)


def should_idle_reap(
    rec: Dict[str, Any],
    now: float,
    heartbeat_timeout: float,
    idle_timeout: float,
) -> bool:
    """Return True when a persistent session is idle long enough to reap."""
    if not rec.get("persistent"):
        return False
    if rec.get("followup_pending"):
        return False
    if not rec.get("terminal") or rec.get("dirty") or rec.get("_reaped"):
        return False
    if (now - rec.get("last_frame", now)) >= heartbeat_timeout:
        return False
    if (now - rec.get("last_activity", now)) <= idle_timeout:
        return False
    return True


def _heartbeat_monitor() -> None:
    """Mark non-terminal agents dirty once their last frame is older than the
    heartbeat timeout (hung, or spawned-but-never-connected). Releases the
    spawn reservation via _count_resolved so the breadth cap can't leak."""
    while not _hb_stop.wait(max(1.0, _hb_timeout() / 3.0)):
        now = time.monotonic()
        timeout = _hb_timeout()
        idle_timeout = _idle_timeout()
        to_reap = []  # (agent_id) of idle persistent agents to kill (outside lock)
        with _registry_lock:
            for aid, rec in _registry.items():
                # Crash/hang detection: a non-terminal agent gone silent.
                if not rec["terminal"] and not rec["dirty"]:
                    if now - rec.get("last_frame", now) > timeout:
                        rec["dirty"] = True
                        _count_resolved(rec)
                        _queue_injection(
                            aid, rec,
                            f"Background sub-agent '{aid}' FAILED: stopped responding "
                            f"(heartbeat lapsed).",
                        )
                        logger.warning(
                            "agent %s heartbeat lapsed (%.0fs > %.0fs) — marked dirty",
                            aid, now - rec["last_frame"], timeout,
                        )
                    continue
                # Idle-reap (PLAN 8f): a PERSISTENT agent that reported a result
                # (terminal) but is still ALIVE (heartbeating → last_frame fresh)
                # and has done no real work for idle_timeout. One-shot agents
                # exit themselves, so they go silent (stale last_frame) and are
                # NOT matched here.
                if should_idle_reap(rec, now, timeout, idle_timeout):
                    rec["_reaped"] = True
                    to_reap.append(aid)
        for aid in to_reap:
            logger.info("Idle-reaping persistent sub-agent %s (idle > %.0fs)", aid, idle_timeout)
            _kill_session(aid)


def ensure_started() -> str:
    """Start the listener (and heartbeat monitor) if needed; return socket path."""
    global _listener, _hb_thread
    with _lock:
        if _listener is None:
            path = _default_socket_path()
            lis = AgentListener(path, on_frame=_on_frame, on_disconnect=_on_disconnect)
            lis.start()
            _listener = lis
            _hb_stop.clear()
            _hb_thread = threading.Thread(
                target=_heartbeat_monitor, name="agent-heartbeat-monitor", daemon=True
            )
            _hb_thread.start()
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


# --- breadth / total caps (Phase 8c) ----------------------------------------

def active_count() -> int:
    """In-flight agents: spawned but not yet finished/crashed."""
    with _registry_lock:
        return max(0, _total_spawned - _total_resolved)


def total_spawned() -> int:
    with _registry_lock:
        return _total_spawned


def can_spawn(max_breadth: int, max_total: int) -> Tuple[bool, Optional[str]]:
    """Check the spawn caps. Returns (ok, reason_if_blocked)."""
    with _registry_lock:
        active = max(0, _total_spawned - _total_resolved)
        total = _total_spawned
    if max_total and total >= max_total:
        return False, f"total agent cap reached ({total}/{max_total} this session)"
    if max_breadth and active >= max_breadth:
        return False, f"concurrent agent cap reached ({active}/{max_breadth} running)"
    return True, None


def note_spawn(agent_id: str) -> None:
    """Record that an agent was spawned (bumps the in-flight count) and
    pre-register a placeholder so the heartbeat monitor can reap it if it never
    connects. Call right after a successful spawn."""
    global _total_spawned
    with _registry_lock:
        _total_spawned += 1
        if agent_id and agent_id not in _registry:
            rec = _blank_record()
            rec["status"] = "spawning"
            _registry[agent_id] = rec


def note_spawn_lifecycle(agent_id: str, persistent: bool) -> None:
    """Annotate a spawned agent record with its intended lifecycle."""
    with _registry_lock:
        rec = _registry.get(agent_id)
        if rec is None:
            rec = _blank_record()
            _registry[agent_id] = rec
        rec["persistent"] = bool(persistent)


def note_followup_sent(agent_id: str) -> None:
    """Mark a persistent agent as having received a new follow-up prompt."""
    now = time.monotonic()
    with _registry_lock:
        rec = _registry.get(agent_id)
        if rec is None:
            rec = _blank_record()
            _registry[agent_id] = rec
        rec["persistent"] = True
        rec["followup_pending"] = True
        rec["terminal"] = False
        rec["dirty"] = False
        rec["_reaped"] = False
        rec["last_followup_sent_at"] = now
        rec["last_frame"] = now
        rec["last_activity"] = now
        if not rec.get("status"):
            rec["status"] = "follow-up pending"


# --- bridge: terminal display (Phase 3) -------------------------------------

def drain_pending_output(limit: Optional[int] = None) -> List[str]:
    """Return buffered output blocks (stdout/result) for display, clearing what
    is returned. With ``limit`` set, return at most that many (oldest first) and
    leave the rest — backpressure so a chatty agent can't dump everything in one
    tick of the live flusher."""
    with _registry_lock:
        if limit is None or limit >= len(_pending_output):
            out = list(_pending_output)
            _pending_output.clear()
        else:
            out = [_pending_output.popleft() for _ in range(limit)]
        return out


def drain_pending_injections() -> List[str]:
    """Return and clear queued completion notices for the orchestrator's next
    LLM turn (Phase 8a async harvest). Call this on the MAIN thread at query-prep
    time, then feed each notice to config.enqueue_next_llm_prefix — keeping
    config's prefix list single-threaded."""
    with _registry_lock:
        out = list(_pending_injections)
        _pending_injections.clear()
        return out


def drain_pending_usage() -> List[Dict[str, Any]]:
    """Return and clear queued sub-agent `usage` deltas (Stage 2 cost telemetry).
    Call on the MAIN thread at query-prep time, then feed each to
    config.record_agent_usage — keeping config cost globals single-threaded."""
    with _registry_lock:
        out = list(_pending_usage)
        _pending_usage.clear()
        return out


def has_active_agents() -> bool:
    """True if any agent is still running (not terminal and not crashed). Gates
    the toolbar so normal (no-agent) prompting is byte-identical."""
    with _registry_lock:
        return any(
            not rec["terminal"] and not rec["dirty"] for rec in _registry.values()
        )


def visibility_snapshot(
    max_active: int = 3, max_recent: int = 2
) -> Dict[str, Any]:
    """Summarize active and recent delegated work for operator-facing surfaces."""
    with _registry_lock:
        active = [
            (aid, rec.get("status"))
            for aid, rec in _registry.items()
            if _classify_record(rec) == "running"
        ]
        completed = 0
        failed = 0
        for rec in _registry.values():
            state = _classify_record(rec)
            if state == "completed":
                completed += 1
            elif state == "failed":
                failed += 1
        recent = list(_recent_terminal_events)[-max(0, int(max_recent)) :]
    return {
        "running_count": len(active),
        "completed_count": completed,
        "failed_count": failed,
        "active": active[: max(0, int(max_active))],
        "recent": recent,
    }


def render_visibility_summary(max_active: int = 2, max_recent: int = 2) -> str:
    """Compact one-line delegated-work summary for the primary orchestrator."""
    snap = visibility_snapshot(max_active=max_active, max_recent=max_recent)
    if (
        snap["running_count"] == 0
        and snap["completed_count"] == 0
        and snap["failed_count"] == 0
        and not snap["recent"]
    ):
        return ""

    parts = [f"agents — running {snap['running_count']}"]
    if snap["completed_count"] or snap["failed_count"]:
        parts.append(
            f"done {snap['completed_count']} failed {snap['failed_count']}"
        )
    if snap["active"]:
        active_text = "; ".join(
            f"{aid}: {status or '…'}" for aid, status in snap["active"]
        )
        parts.append(f"active {active_text}")
    if snap["recent"]:
        recent_text = "; ".join(
            f"{'✓' if event['outcome'] == 'ok' else '✗'} {event['agent_id']} {event['summary']}"
            for event in snap["recent"]
        )
        parts.append(f"recent {recent_text}")
    return " | ".join(parts)


def render_toolbar() -> str:
    """One-line live status of active agents for the prompt_toolkit toolbar.

    Returns "" when no agents are active so the toolbar is hidden in normal use.
    """
    with _registry_lock:
        has_visible_startup = any(
            rec.get("status") == "spawning" and not rec.get("terminal") and not rec.get("dirty")
            for rec in _registry.values()
        )
    if not has_visible_startup and not has_active_agents():
        return ""
    summary = render_visibility_summary()
    if not summary:
        return ""
    return summary


# --- lifecycle / tests ------------------------------------------------------

def stop() -> None:
    global _listener, _hb_thread
    _hb_stop.set()
    with _lock:
        lis = _listener
        _listener = None
        hb = _hb_thread
        _hb_thread = None
    if lis is not None:
        lis.stop()
    if hb is not None:
        hb.join(timeout=2.0)


def reset_for_test() -> None:
    """Stop the listener + heartbeat monitor and clear all state (test-only)."""
    global _total_spawned, _total_resolved
    stop()
    with _registry_lock:
        _registry.clear()
        _pending_output.clear()
        _pending_injections.clear()
        _recent_terminal_events.clear()
        _total_spawned = 0
        _total_resolved = 0
