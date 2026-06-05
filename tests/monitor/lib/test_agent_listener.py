"""Tests for the AF_UNIX agent listener (PLAN_AGENT_ORCHESTRATION Phase 2).

Uses a plain socket client (no subprocess) to exercise the transport: connect,
stream frames, observe the sink, and verify clean-vs-dirty disconnect detection
and socket teardown.
"""

import os
import socket
import threading
import time

import pytest

from monitor.lib import agent_protocol as ap
from monitor.lib.agent_listener import AgentListener


def _wait(predicate, timeout=2.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture
def listener(tmp_path):
    frames = []
    disconnects = []
    lock = threading.Lock()

    def on_frame(frame, conn_id):
        with lock:
            frames.append((conn_id, frame))

    def on_disconnect(conn_id, agent_id, dirty):
        with lock:
            disconnects.append((conn_id, agent_id, dirty))

    sock_path = str(tmp_path / "orch.sock")
    lis = AgentListener(sock_path, on_frame=on_frame, on_disconnect=on_disconnect)
    lis.start()
    yield lis, frames, disconnects, lock, sock_path
    lis.stop()


def _client(sock_path):
    c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    c.connect(sock_path)
    return c


def test_socket_file_created_and_removed(listener):
    lis, _frames, _dc, _lock, sock_path = listener
    assert os.path.exists(sock_path)
    lis.stop()
    assert not os.path.exists(sock_path)


def test_frames_reach_sink(listener):
    lis, frames, _dc, lock, sock_path = listener
    c = _client(sock_path)
    c.sendall(ap.encode(ap.HELLO, "agentX", 1, {"depth": 1, "cmd": "x", "pid": 1, "name": "n"}))
    c.sendall(ap.encode(ap.STATUS, "agentX", 2, {"label": "working"}))
    assert _wait(lambda: len(frames) >= 2)
    with lock:
        types = [f["type"] for _cid, f in frames]
    assert ap.HELLO in types and ap.STATUS in types
    c.close()


def test_partial_writes_reassembled_over_socket(listener):
    lis, frames, _dc, lock, sock_path = listener
    c = _client(sock_path)
    blob = ap.encode(ap.STDOUT, "agentX", 5, {"chunk": "a long-ish chunk of output"})
    # Dribble the bytes to force the decoder to reassemble across recv() calls.
    for i in range(0, len(blob), 3):
        c.sendall(blob[i : i + 3])
        time.sleep(0.001)
    assert _wait(lambda: len(frames) >= 1)
    with lock:
        assert frames[0][1]["body"]["chunk"] == "a long-ish chunk of output"
    c.close()


def test_clean_disconnect_after_exit(listener):
    lis, _frames, disconnects, lock, sock_path = listener
    c = _client(sock_path)
    c.sendall(ap.encode(ap.HELLO, "agentClean", 1, {"depth": 1, "cmd": "x", "pid": 1, "name": "n"}))
    c.sendall(ap.encode(ap.EXIT, "agentClean", 2, {"code": 0}))
    time.sleep(0.05)
    c.close()
    assert _wait(lambda: len(disconnects) >= 1)
    with lock:
        conn_id, agent_id, dirty = disconnects[-1]
    assert agent_id == "agentClean"
    assert dirty is False  # saw a terminal (exit) frame → clean


def test_dirty_disconnect_without_exit(listener):
    lis, _frames, disconnects, lock, sock_path = listener
    c = _client(sock_path)
    c.sendall(ap.encode(ap.HELLO, "agentCrash", 1, {"depth": 1, "cmd": "x", "pid": 1, "name": "n"}))
    c.sendall(ap.encode(ap.STATUS, "agentCrash", 2, {"label": "mid-task"}))
    time.sleep(0.05)
    c.close()  # close WITHOUT an exit frame → crash
    assert _wait(lambda: len(disconnects) >= 1)
    with lock:
        _conn_id, agent_id, dirty = disconnects[-1]
    assert agent_id == "agentCrash"
    assert dirty is True


def test_multiple_connections_distinct_ids(listener):
    lis, frames, _dc, lock, sock_path = listener
    a = _client(sock_path)
    b = _client(sock_path)
    a.sendall(ap.encode(ap.STATUS, "a", 1, {"label": "A"}))
    b.sendall(ap.encode(ap.STATUS, "b", 1, {"label": "B"}))
    assert _wait(lambda: len(frames) >= 2)
    with lock:
        conn_ids = {cid for cid, _f in frames}
    assert len(conn_ids) == 2
    a.close()
    b.close()


def test_protocol_error_closes_connection(listener):
    lis, _frames, disconnects, lock, sock_path = listener
    c = _client(sock_path)
    # A length prefix that exceeds the cap → ProtocolError → reader drops conn.
    c.sendall((ap.MAX_FRAME_BYTES + 1).to_bytes(4, "big") + b"{}")
    assert _wait(lambda: len(disconnects) >= 1)
    with lock:
        # dirty=True (no terminal frame seen)
        assert disconnects[-1][2] is True
    c.close()
