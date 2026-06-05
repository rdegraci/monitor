"""Tests for Phase 8c breadth/total caps and Phase 5 heartbeat-lapse detection
in agent_orchestrator.
"""

import time

import pytest

from monitor.lib import agent_orchestrator as orch
from monitor.lib.agent_reporter import AgentReporter


def _wait(predicate, timeout=3.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture(autouse=True)
def _clean():
    orch.reset_for_test()
    yield
    orch.reset_for_test()


# --- caps -------------------------------------------------------------------

def test_breadth_cap_blocks_when_full():
    # 2 in-flight spawns, breadth cap of 2 → next is blocked.
    orch.note_spawn("a")
    orch.note_spawn("b")
    assert orch.active_count() == 2
    ok, reason = orch.can_spawn(max_breadth=2, max_total=100)
    assert ok is False
    assert "concurrent" in reason


def test_total_cap_blocks():
    orch.note_spawn("a")
    orch.note_spawn("b")
    ok, reason = orch.can_spawn(max_breadth=100, max_total=2)
    assert ok is False
    assert "total" in reason


def test_resolved_agent_frees_breadth():
    path = orch.ensure_started()
    orch.note_spawn("x")
    assert orch.active_count() == 1
    # An agent that connects and finishes is no longer in-flight.
    r = AgentReporter(path, "x"); r.connect()
    r.result(ok=True, summary="done"); r.close()
    assert _wait(lambda: orch.active_count() == 0)
    ok, _ = orch.can_spawn(max_breadth=1, max_total=100)
    assert ok is True


def test_default_caps_allow_only_one_agent(monkeypatch):
    """Safeguard: by default at most ONE sub-agent is ever spawned per session
    (breadth 1 AND total 1)."""
    from monitor.core.agent_tools import _agent_caps
    monkeypatch.delenv("MONITOR_AGENT_MAX_BREADTH", raising=False)
    monkeypatch.delenv("MONITOR_AGENT_MAX_TOTAL", raising=False)
    breadth, total = _agent_caps()
    assert breadth == 1
    assert total == 1
    # After one spawn, BOTH caps block a second (total cap checked first).
    orch.note_spawn("only")
    ok, reason = orch.can_spawn(breadth, total)
    assert ok is False
    assert "total" in reason or "concurrent" in reason


def test_zero_cap_disables():
    for i in range(5):
        orch.note_spawn(f"a{i}")
    ok, _ = orch.can_spawn(max_breadth=0, max_total=0)
    assert ok is True  # 0 = disabled


# --- heartbeat-lapse (Phase 5) ----------------------------------------------

def test_heartbeat_lapse_marks_dirty(monkeypatch):
    # Tiny timeout so the monitor reaps quickly.
    monkeypatch.setenv("MONITOR_AGENT_HEARTBEAT_TIMEOUT", "0.3")
    path = orch.ensure_started()
    r = AgentReporter(path, "hang")
    r.connect()
    r.status("working")
    # Do NOT send further frames or heartbeats; the monitor should mark it dirty.
    assert _wait(lambda: (orch.agent_record("hang") or {}).get("dirty") is True, timeout=4)
    rec = orch.agent_record("hang")
    assert rec["dirty"] is True
    assert rec["terminal"] is False
    # Reaping released the in-flight count too (it was counted resolved).
    r.close()


def test_never_connected_spawn_is_reaped(monkeypatch):
    monkeypatch.setenv("MONITOR_AGENT_HEARTBEAT_TIMEOUT", "0.3")
    orch.ensure_started()
    orch.note_spawn("ghost")  # placeholder; never connects
    assert orch.active_count() == 1
    # Heartbeat monitor reaps the stale placeholder → frees the in-flight count.
    assert _wait(lambda: orch.active_count() == 0, timeout=4)
    rec = orch.agent_record("ghost")
    assert rec["dirty"] is True


def test_idle_reaper_kills_persistent_idle_agent(monkeypatch):
    # Idle timeout tiny; heartbeat timeout large so the agent counts as ALIVE
    # (still heartbeating) rather than crashed.
    monkeypatch.setenv("MONITOR_AGENT_IDLE_TIMEOUT", "0.3")
    monkeypatch.setenv("MONITOR_AGENT_HEARTBEAT_TIMEOUT", "5")
    killed = []
    monkeypatch.setattr(orch, "_kill_session", lambda aid: killed.append(aid))

    path = orch.ensure_started()
    r = AgentReporter(path, "persist")
    r.connect()
    r.result(ok=True, summary="done task 1")   # terminal; last_activity set here
    r.start_heartbeat(interval=0.05)            # stays ALIVE but does no work
    # The reaper (runs every ~hb/3) should kill it once idle > 0.3s while alive.
    assert _wait(lambda: "persist" in killed, timeout=6)
    r.stop_heartbeat()
    r.close()


def test_heartbeat_keeps_agent_alive(monkeypatch):
    monkeypatch.setenv("MONITOR_AGENT_HEARTBEAT_TIMEOUT", "0.5")
    path = orch.ensure_started()
    r = AgentReporter(path, "alive")
    r.connect()
    r.start_heartbeat(interval=0.1)  # heartbeats faster than the timeout
    # Should stay alive (not dirty) across a couple of timeout windows.
    time.sleep(1.2)
    rec = orch.agent_record("alive")
    assert rec["dirty"] is False
    r.stop_heartbeat()
    r.close()
