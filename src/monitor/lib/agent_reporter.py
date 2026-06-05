"""Child-side reporting client for `monitor --agent` sub-agents.

Implements the child half of Phase 0.5 in docs/cache/PLAN_AGENT_ORCHESTRATION.md:
when a monitor instance runs in `--agent` mode, it connects back to its parent
orchestrator's AF_UNIX socket and emits framed `hello`/`status`/`stdout`/
`result`/`error`/`exit`/`heartbeat` frames using ``agent_protocol``.

Design rules:
- **Never crash the child.** If the socket is missing or a send fails, the
  reporter degrades to a no-op and the agent keeps running as an ordinary
  monitor instance. Orchestration is best-effort telemetry, not a hard
  dependency.
- **Monotonic seq, serialized sends.** A lock guards the seq counter and the
  socket so the heartbeat thread and the main thread never interleave a frame.
- stdlib + agent_protocol only; reads its wiring from the environment
  (no monitor.config import → no import cycle).

Environment (set by the spawner — see screen_handler):
- ``MONITOR_AGENT_SOCKET`` — path to the orchestrator's listening socket.
- ``MONITOR_AGENT_ID``     — stable id for this agent (falls back to pid).
- ``MONITOR_AGENT_DEPTH``  — recursion depth, included in the hello frame.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
from typing import Any, Optional

from monitor.lib import agent_protocol as ap

logger = logging.getLogger(__name__)

_DEFAULT_HEARTBEAT_SECONDS = 15.0


class AgentReporter:
    """Best-effort frame emitter from a sub-agent to its orchestrator."""

    def __init__(self, socket_path: str, agent_id: str, *, name: str = "", depth: int = 0):
        self.socket_path = socket_path
        self.agent_id = agent_id
        self.name = name or agent_id
        self.depth = depth

        self._sock: Optional[socket.socket] = None
        self._seq = 0
        self._lock = threading.Lock()
        self._connected = False
        self._closed = False
        self._hb_thread: Optional[threading.Thread] = None
        self._hb_stop = threading.Event()

    # --- connection ---------------------------------------------------------

    def connect(self) -> bool:
        """Connect and send the hello frame. Returns False (no-op) on failure."""
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(self.socket_path)
        except OSError as e:
            logger.info("AgentReporter: no orchestrator at %s (%s); running unreported",
                        self.socket_path, e)
            return False
        self._sock = s
        self._connected = True
        ok = self._send(ap.hello(
            self.agent_id, self._next_seq(),
            depth=self.depth, cmd=self.name, pid=os.getpid(), name=self.name,
        ))
        if ok:
            logger.info("AgentReporter connected to orchestrator at %s (agent_id=%s)",
                        self.socket_path, self.agent_id)
        return ok

    @property
    def connected(self) -> bool:
        return self._connected and not self._closed

    # --- emitting -----------------------------------------------------------

    def status(self, label: str) -> None:
        self._emit(ap.status(self.agent_id, self._next_seq(), label))

    def emit_stdout(self, chunk: str) -> None:
        self._emit(ap.stdout(self.agent_id, self._next_seq(), chunk))

    def result(self, *, ok: bool, summary: str, data: Optional[Any] = None) -> None:
        self._emit(ap.result(self.agent_id, self._next_seq(), ok=ok, summary=summary, data=data))

    def report_error(self, *, kind: str, message: str, recoverable: bool = False) -> None:
        self._emit(ap.error(self.agent_id, self._next_seq(), kind=kind, message=message,
                            recoverable=recoverable))

    def close(self, code: int = 0) -> None:
        """Send a clean exit frame, stop the heartbeat, and close the socket."""
        if self._closed:
            return
        self.stop_heartbeat()
        self._emit(ap.exit_frame(self.agent_id, self._next_seq(), code))
        self._closed = True
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
        self._connected = False

    # --- heartbeat ----------------------------------------------------------

    def start_heartbeat(self, interval: float = _DEFAULT_HEARTBEAT_SECONDS) -> None:
        if not self.connected or self._hb_thread is not None:
            return
        self._hb_stop.clear()

        def _loop():
            while not self._hb_stop.wait(interval):
                self._emit(ap.heartbeat(self.agent_id, self._next_seq()))

        self._hb_thread = threading.Thread(target=_loop, name="agent-heartbeat", daemon=True)
        self._hb_thread.start()

    def stop_heartbeat(self) -> None:
        self._hb_stop.set()
        t = self._hb_thread
        if t is not None:
            t.join(timeout=1.0)
            self._hb_thread = None

    # --- internals ----------------------------------------------------------

    def _next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def _emit(self, frame: dict) -> None:
        """Best-effort send; never raises into agent code."""
        if not self._connected or self._closed:
            return
        self._send(frame)

    def _send(self, frame: dict) -> bool:
        with self._lock:
            if self._sock is None:
                return False
            try:
                self._sock.sendall(ap.encode_frame(frame))
                return True
            except (OSError, ap.ProtocolError) as e:
                logger.warning("AgentReporter send failed (%s); marking disconnected", e)
                self._connected = False
                return False


# --- process-wide active reporter ------------------------------------------
# A spawned sub-agent has exactly one reporter for its lifetime. The main
# conversation loop reaches it through this singleton to emit per-turn results.
_active: Optional[AgentReporter] = None


def set_active(reporter: Optional[AgentReporter]) -> None:
    global _active
    _active = reporter


def active() -> Optional[AgentReporter]:
    return _active


def from_env() -> Optional[AgentReporter]:
    """Build a connected reporter from the environment, or None if not applicable.

    Returns None when ``MONITOR_AGENT_SOCKET`` is unset (not a spawned sub-agent)
    or the connection fails — callers proceed as an ordinary monitor instance.
    """
    sock_path = os.environ.get("MONITOR_AGENT_SOCKET")
    if not sock_path:
        return None
    agent_id = os.environ.get("MONITOR_AGENT_ID") or f"agent-{os.getpid()}"
    try:
        depth = int(os.environ.get("MONITOR_AGENT_DEPTH", "0"))
    except (TypeError, ValueError):
        depth = 0
    reporter = AgentReporter(sock_path, agent_id, name=agent_id, depth=depth)
    if not reporter.connect():
        return None
    return reporter
