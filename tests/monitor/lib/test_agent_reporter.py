"""Tests for the child-side AgentReporter (PLAN_AGENT_ORCHESTRATION Phase 0.5).

Exercises the reporter against a real AgentListener over a loopback AF_UNIX
socket — completing the protocol round-trip (child emits → orchestrator
receives) without spawning a subprocess.
"""

import threading
import time

import pytest

from monitor.lib import agent_protocol as ap
from monitor.lib.agent_listener import AgentListener
from monitor.lib.agent_reporter import AgentReporter, from_env


def _wait(predicate, timeout=2.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture
def wired(tmp_path):
    frames = []
    disconnects = []
    lock = threading.Lock()

    def on_frame(frame, conn_id):
        with lock:
            frames.append(frame)

    def on_disconnect(conn_id, agent_id, dirty):
        with lock:
            disconnects.append((agent_id, dirty))

    sock_path = str(tmp_path / "orch.sock")
    lis = AgentListener(sock_path, on_frame=on_frame, on_disconnect=on_disconnect)
    lis.start()
    yield sock_path, frames, disconnects, lock
    lis.stop()


def _types(frames, lock):
    with lock:
        return [f["type"] for f in frames]


def test_connect_sends_hello(wired):
    sock_path, frames, _dc, lock = wired
    r = AgentReporter(sock_path, "ag1", name="ag1", depth=2)
    assert r.connect() is True
    assert _wait(lambda: ap.HELLO in _types(frames, lock))
    with lock:
        hello = frames[0]
    assert hello["agent_id"] == "ag1"
    assert hello["body"]["depth"] == 2
    r.close()


def test_full_lifecycle_round_trip(wired):
    sock_path, frames, disconnects, lock = wired
    r = AgentReporter(sock_path, "ag2")
    assert r.connect()
    r.status("phase one")
    r.emit_stdout("some output block")
    r.result(ok=True, summary="did the thing", data={"n": 3})
    r.close(0)
    assert _wait(lambda: ap.EXIT in _types(frames, lock))
    types = _types(frames, lock)
    assert types == [ap.HELLO, ap.STATUS, ap.STDOUT, ap.RESULT, ap.EXIT]
    with lock:
        res = next(f for f in frames if f["type"] == ap.RESULT)
    assert res["body"]["summary"] == "did the thing"
    assert res["body"]["data"] == {"n": 3}
    # Clean disconnect: saw a terminal frame.
    assert _wait(lambda: len(disconnects) >= 1)
    with lock:
        assert disconnects[-1] == ("ag2", False)


def test_seq_is_monotonic(wired):
    sock_path, frames, _dc, lock = wired
    r = AgentReporter(sock_path, "ag3")
    r.connect()
    r.status("a")
    r.status("b")
    r.close()
    assert _wait(lambda: ap.EXIT in _types(frames, lock))
    with lock:
        seqs = [f["seq"] for f in frames]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)  # no duplicates


def test_missing_socket_is_noop_not_crash(tmp_path):
    r = AgentReporter(str(tmp_path / "nonexistent.sock"), "ag4")
    assert r.connect() is False
    # All emit calls must be safe no-ops.
    r.status("x")
    r.emit_stdout("y")
    r.result(ok=False, summary="z")
    r.close()
    assert r.connected is False


def test_heartbeat_emits(wired):
    sock_path, frames, _dc, lock = wired
    r = AgentReporter(sock_path, "ag5")
    r.connect()
    r.start_heartbeat(interval=0.02)
    assert _wait(lambda: ap.HEARTBEAT in _types(frames, lock))
    r.stop_heartbeat()
    r.close()


def test_from_env_none_without_socket(monkeypatch):
    monkeypatch.delenv("MONITOR_AGENT_SOCKET", raising=False)
    assert from_env() is None


def test_from_env_builds_connected_reporter(wired, monkeypatch):
    sock_path, frames, _dc, lock = wired
    monkeypatch.setenv("MONITOR_AGENT_SOCKET", sock_path)
    monkeypatch.setenv("MONITOR_AGENT_ID", "envagent")
    monkeypatch.setenv("MONITOR_AGENT_DEPTH", "3")
    r = from_env()
    assert r is not None
    assert r.agent_id == "envagent"
    assert r.depth == 3
    assert _wait(lambda: ap.HELLO in _types(frames, lock))
    r.close()


def test_report_error_frame(wired):
    sock_path, frames, _dc, lock = wired
    r = AgentReporter(sock_path, "ag6")
    r.connect()
    r.report_error(kind="ValueError", message="boom", recoverable=False)
    assert _wait(lambda: ap.ERROR in _types(frames, lock))
    with lock:
        err = next(f for f in frames if f["type"] == ap.ERROR)
    assert err["body"]["kind"] == "ValueError"
    assert err["body"]["message"] == "boom"
    r.close()
