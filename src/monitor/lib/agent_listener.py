"""AF_UNIX listener for the sub-agent frame protocol (transport layer).

Implements Phase 2 of docs/cache/PLAN_AGENT_ORCHESTRATION.md: the orchestrator
side of the socket. One listener per orchestrator owns one socket file; each
`monitor --agent` child connects and streams frames, which are decoded with
``agent_protocol.FrameDecoder`` and handed to a pluggable ``on_frame`` sink.

The sink is deliberately abstract so Phase 3 (the prompt_toolkit bridge) can plug
its lock-guarded shared state in here without this module knowing anything about
the UI. By default frames are logged.

Threading model:
- one **accept thread** owns the server socket and spawns…
- one **reader thread per connection**, which decodes frames and calls the sink.

Reader threads are the ONLY callers of the sink; the sink is responsible for its
own locking. This module locks only its own connection registry.

stdlib-only (socket/threading/os/logging) + agent_protocol → imports cleanly
with no monitor.config dependency (no import cycle).
"""

from __future__ import annotations

import logging
import os
import socket
import threading
from typing import Any, Callable, Dict, Optional

from monitor.lib import agent_protocol as ap

logger = logging.getLogger(__name__)

_RECV_SIZE = 65536

# on_frame(frame: dict, conn_id: int) -> None
FrameSink = Callable[[Dict[str, Any], int], None]
# on_disconnect(conn_id: int, agent_id: Optional[str], dirty: bool) -> None
DisconnectSink = Callable[[int, Optional[str], bool], None]


class AgentListener:
    """Listens on an AF_UNIX socket and streams decoded frames to a sink.

    ``dirty`` disconnect = the connection closed (or errored) WITHOUT having sent
    a terminal frame (result/error/exit). That is the authoritative crash signal
    per the PLAN — Phase 5 maps it to conversation-history rollback.
    """

    def __init__(
        self,
        socket_path: str,
        on_frame: Optional[FrameSink] = None,
        on_disconnect: Optional[DisconnectSink] = None,
        recv_size: int = _RECV_SIZE,
    ):
        self.socket_path = socket_path
        self._on_frame = on_frame or self._log_frame
        self._on_disconnect = on_disconnect
        self._recv_size = recv_size

        self._srv: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._running = False
        self._next_conn_id = 0
        self._lock = threading.Lock()
        # conn_id -> {"sock", "agent_id", "seen_terminal", "thread"}
        self._conns: Dict[int, Dict[str, Any]] = {}

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Bind the socket (unlinking any stale file first) and begin accepting."""
        parent = os.path.dirname(os.path.abspath(self.socket_path)) or "."
        try:
            os.makedirs(parent, mode=0o700, exist_ok=True)
        except OSError:
            logger.debug("AgentListener: could not ensure dir %s", parent, exc_info=True)
        # Stale-socket cleanup: a leftover file from a crashed prior run would
        # make bind() fail with EADDRINUSE.
        self._unlink_quietly()

        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.socket_path)
        try:
            os.chmod(self.socket_path, 0o600)
        except OSError:
            logger.debug("AgentListener: could not chmod %s", self.socket_path, exc_info=True)
        srv.listen(64)
        self._srv = srv
        self._running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="agent-listener-accept", daemon=True
        )
        self._accept_thread.start()
        logger.info("AgentListener started on %s", self.socket_path)

    def stop(self, timeout: float = 2.0) -> None:
        """Stop accepting, close all connections, join threads, unlink the socket."""
        self._running = False
        # Closing the server socket unblocks accept().
        if self._srv is not None:
            try:
                self._srv.close()
            except OSError:
                pass
        # Close all live connection sockets to unblock reader threads.
        with self._lock:
            conns = list(self._conns.values())
        for c in conns:
            try:
                c["sock"].close()
            except OSError:
                pass
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=timeout)
        for c in conns:
            t = c.get("thread")
            if t is not None:
                t.join(timeout=timeout)
        self._unlink_quietly()
        logger.info("AgentListener stopped (%s)", self.socket_path)

    # --- accept / read loops ------------------------------------------------

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                break  # server socket closed by stop()
            with self._lock:
                conn_id = self._next_conn_id
                self._next_conn_id += 1
                t = threading.Thread(
                    target=self._reader_loop,
                    args=(conn, conn_id),
                    name=f"agent-reader-{conn_id}",
                    daemon=True,
                )
                self._conns[conn_id] = {
                    "sock": conn,
                    "agent_id": None,
                    "seen_terminal": False,
                    "thread": t,
                }
            t.start()

    def _reader_loop(self, conn: socket.socket, conn_id: int) -> None:
        decoder = ap.FrameDecoder()
        try:
            while self._running:
                try:
                    data = conn.recv(self._recv_size)
                except OSError:
                    break
                if not data:
                    break  # peer closed
                try:
                    frames = decoder.feed(data)
                except ap.ProtocolError as e:
                    logger.warning("AgentListener conn %d protocol error: %s", conn_id, e)
                    break
                for frame in frames:
                    self._note_frame(conn_id, frame)
                    try:
                        self._on_frame(frame, conn_id)
                    except Exception:
                        logger.exception("AgentListener on_frame sink raised (conn %d)", conn_id)
        finally:
            self._close_conn(conn_id, conn)

    # --- bookkeeping --------------------------------------------------------

    def _note_frame(self, conn_id: int, frame: Dict[str, Any]) -> None:
        with self._lock:
            c = self._conns.get(conn_id)
            if c is None:
                return
            if frame.get("type") == ap.HELLO and not c["agent_id"]:
                c["agent_id"] = frame.get("agent_id")
            elif c["agent_id"] is None:
                # Adopt the agent_id from the first frame even if not a hello.
                c["agent_id"] = frame.get("agent_id")
            if ap.is_terminal(frame):
                c["seen_terminal"] = True

    def _close_conn(self, conn_id: int, conn: socket.socket) -> None:
        try:
            conn.close()
        except OSError:
            pass
        with self._lock:
            c = self._conns.pop(conn_id, None)
        if c is None:
            return
        agent_id = c["agent_id"]
        dirty = not c["seen_terminal"]
        logger.info(
            "AgentListener conn %d closed (agent_id=%s, dirty=%s)", conn_id, agent_id, dirty
        )
        if self._on_disconnect is not None:
            try:
                self._on_disconnect(conn_id, agent_id, dirty)
            except Exception:
                logger.exception("AgentListener on_disconnect sink raised (conn %d)", conn_id)

    # --- orchestrator → child (cancel/control) ------------------------------

    def send_frame(self, conn_id: int, frame: Dict[str, Any]) -> bool:
        """Send a frame to a connected child (e.g. a cancel). Returns success."""
        with self._lock:
            c = self._conns.get(conn_id)
        if c is None:
            return False
        try:
            c["sock"].sendall(ap.encode_frame(frame))
            return True
        except OSError as e:
            logger.warning("AgentListener send to conn %d failed: %s", conn_id, e)
            return False

    @property
    def connection_count(self) -> int:
        with self._lock:
            return len(self._conns)

    # --- helpers ------------------------------------------------------------

    def _unlink_quietly(self) -> None:
        try:
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
        except OSError:
            logger.debug("AgentListener: could not unlink %s", self.socket_path, exc_info=True)

    @staticmethod
    def _log_frame(frame: Dict[str, Any], conn_id: int) -> None:
        logger.info(
            "agent frame [conn %d] type=%s agent=%s seq=%s body=%s",
            conn_id, frame.get("type"), frame.get("agent_id"), frame.get("seq"), frame.get("body"),
        )
