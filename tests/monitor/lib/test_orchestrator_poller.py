import json
import socket
import threading
import time
from datetime import datetime
from queue import Queue, Empty
from pathlib import Path
import tempfile
from uuid import uuid4
from typing import Any, Dict, List

import pytest

from monitor.lib.orchestrator_poller import OrchestratorPoller


def _start_simple_uds_server(sock_path: Path, payload_getter, stop_event: threading.Event, start_event: threading.Event = None) -> threading.Thread:
    """Start a simple UDS server that replies with JSON from payload_getter() on each connection.

    The server runs in a daemon thread and will exit when stop_event is set.
    If start_event is provided, it will be set after the server has successfully bound the socket.
    """

    def _server():
        if sock_path.exists():
            try:
                sock_path.unlink()
            except Exception:
                pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(sock_path))
            server.listen(5)
            server.settimeout(0.2)
            try:
                # Set permissive but user-only recommended in production
                sock_path.chmod(0o600)
            except Exception:
                pass
            if start_event is not None:
                try:
                    start_event.set()
                except Exception:
                    pass
            while not stop_event.is_set():
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                except Exception:
                    break
                try:
                    # Read until newline (client sends a newline)
                    try:
                        data = b""
                        while True:
                            chunk = conn.recv(4096)
                            if not chunk:
                                break
                            data += chunk
                            if b"\n" in chunk:
                                break
                    except Exception:
                        pass

                    payload = payload_getter()
                    if payload is None:
                        # send empty response
                        try:
                            conn.sendall(b"\n")
                        except Exception:
                            pass
                    else:
                        try:
                            bs = json.dumps(payload).encode("utf-8") + b"\n"
                            conn.sendall(bs)
                        except Exception:
                            pass
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
        finally:
            try:
                server.close()
            except Exception:
                pass
            try:
                if sock_path.exists():
                    sock_path.unlink()
            except Exception:
                pass

    t = threading.Thread(target=_server, daemon=True)
    t.start()
    return t


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def test_orchestrator_poller_delivers_state_changes(tmp_path):
    sock = Path(tempfile.gettempdir()) / f"agent-status-{uuid4().hex[:8]}.sock"
    stop_event = threading.Event()

    # Use a mutable list container so the server can read the current payload
    current = {"payload": {"state": "working", "since": _now_iso()}}

    def getter():
        return dict(current["payload"])

    start_event = threading.Event()
    srv_thread = _start_simple_uds_server(sock, getter, stop_event, start_event=start_event)

    if not start_event.wait(timeout=2.0):
        stop_event.set()
        srv_thread.join(timeout=1)
        raise RuntimeError('UDS socket not created by test server')

    q = Queue()
    poller = OrchestratorPoller("session-1", str(sock), queue=q, poll_interval=0.1, connect_timeout=0.5, idle_confirm=0)
    poller.start()

    try:
        # First event should be working
        ev = q.get(timeout=2)
        assert ev.get("state") == "working"
        assert ev.get("session") == "session-1"

        # Change to idle and ensure poller delivers the new state
        time.sleep(0.1)
        current["payload"] = {"state": "idle", "since": _now_iso()}

        ev2 = q.get(timeout=2)
        assert ev2.get("state") == "idle"
        assert poller.wait_for_state("idle", timeout=2)
    finally:
        poller.stop()
        stop_event.set()
        srv_thread.join(timeout=1)


def test_orchestrator_poller_wait_timeout(tmp_path):
    sock = Path(tempfile.gettempdir()) / f"agent2-status-{uuid4().hex[:8]}.sock"
    stop_event = threading.Event()

    # Server will continuously report 'working'
    current = {"payload": {"state": "working", "since": _now_iso()}}

    def getter():
        return dict(current["payload"])

    start_event = threading.Event()
    srv_thread = _start_simple_uds_server(sock, getter, stop_event, start_event=start_event)

    if not start_event.wait(timeout=2.0):
        stop_event.set()
        srv_thread.join(timeout=1)
        raise RuntimeError('UDS socket not created by test server')

    q = Queue()
    poller = OrchestratorPoller("session-2", str(sock), queue=q, poll_interval=0.1, connect_timeout=0.5, idle_confirm=0)
    poller.start()

    try:
        # wait_for_state should time out because we never switch to idle
        got = poller.wait_for_state("idle", timeout=0.5)
        assert got is False
    finally:
        poller.stop()
        stop_event.set()
        srv_thread.join(timeout=1)
