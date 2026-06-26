"""Tests for the orchestrator-side singleton (PLAN_AGENT_ORCHESTRATION Phase 0.5).

Drives the orchestrator listener + registry with a real AgentReporter over a
loopback socket (no subprocess).
"""

import time

import pytest

from monitor.lib import agent_protocol as ap
from monitor.lib import agent_orchestrator as orch
from monitor.lib.agent_reporter import AgentReporter


def _wait(predicate, timeout=2.0, interval=0.01):
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


def test_ensure_started_idempotent_returns_path():
    p1 = orch.ensure_started()
    p2 = orch.ensure_started()
    assert p1 == p2
    assert orch.is_running()
    assert orch.socket_path() == p1


def test_records_status_and_result():
    path = orch.ensure_started()
    r = AgentReporter(path, "agA")
    assert r.connect()
    r.status("indexing")
    r.result(ok=True, summary="found 3 things", data=[1, 2, 3])
    assert _wait(lambda: (orch.agent_record("agA") or {}).get("results"))
    rec = orch.agent_record("agA")
    assert rec["status"] == "indexing"
    assert rec["results"][0]["summary"] == "found 3 things"
    assert rec["terminal"] is True
    r.close()


def test_all_statuses_snapshot():
    path = orch.ensure_started()
    a = AgentReporter(path, "a1"); a.connect(); a.status("alpha")
    b = AgentReporter(path, "b2"); b.connect(); b.status("beta")
    # Wait for the status frames themselves to land (not just the agents to
    # register on hello) — otherwise this races the status delivery.
    assert _wait(lambda: orch.all_statuses().get("a1") == "alpha"
                 and orch.all_statuses().get("b2") == "beta")
    statuses = orch.all_statuses()
    assert statuses["a1"] == "alpha"
    assert statuses["b2"] == "beta"
    a.close(); b.close()


def test_dirty_disconnect_recorded():
    path = orch.ensure_started()
    r = AgentReporter(path, "crashy")
    r.connect()
    r.status("mid-task")
    # Hard-close the underlying socket WITHOUT sending exit (simulate crash).
    r._sock.close()
    assert _wait(lambda: (orch.agent_record("crashy") or {}).get("dirty") is True)
    rec = orch.agent_record("crashy")
    assert rec["dirty"] is True
    assert rec["terminal"] is False


def test_pending_output_drains_stdout_and_result():
    path = orch.ensure_started()
    r = AgentReporter(path, "outA")
    r.connect()
    r.emit_stdout("line one\nline two")
    r.result(ok=True, summary="all good")
    # Wait until the (terminal) result frame is recorded, then drain once.
    assert _wait(lambda: (orch.agent_record("outA") or {}).get("terminal"))
    drained = orch.drain_pending_output()
    text = "\n".join(drained)
    assert "line one" in text and "line two" in text
    assert "✓ all good" in text
    # Drain is destructive — a second drain is empty.
    assert orch.drain_pending_output() == []
    r.close()


def test_drain_pending_output_respects_limit():
    # Seed pending output directly via a reporter's stdout frames.
    path = orch.ensure_started()
    r = AgentReporter(path, "many"); r.connect()
    for i in range(10):
        r.emit_stdout(f"line {i}")
    assert _wait(lambda: _buffered_count() >= 10)
    first = orch.drain_pending_output(limit=4)
    assert len(first) == 4
    rest = orch.drain_pending_output()  # no limit → the remaining 6
    assert len(rest) == 6
    assert orch.drain_pending_output() == []
    r.close()


def _buffered_count():
    # Count without draining (test helper).
    import monitor.lib.agent_orchestrator as _o
    with _o._registry_lock:
        return len(_o._pending_output)


def test_render_toolbar_active_then_empty():
    path = orch.ensure_started()
    assert orch.render_toolbar() == ""  # no agents
    r = AgentReporter(path, "tb1")
    r.connect()
    r.status("scanning")
    # Wait for the status frame to land (not just for the agent to register).
    assert _wait(lambda: "scanning" in (orch.render_toolbar() or ""))
    bar = orch.render_toolbar()
    assert "running 1" in bar
    assert "tb1" in bar and "scanning" in bar
    # After a terminal frame the agent is no longer active → toolbar empties.
    r.result(ok=True, summary="done")
    r.close()
    assert _wait(lambda: not orch.has_active_agents())
    assert orch.render_toolbar() == ""



def test_render_toolbar_shows_spawning_agent_before_first_frame():
    orch.note_spawn("spawn1")
    bar = orch.render_toolbar()
    assert "running 1" in bar
    assert "spawn1: spawning" in bar

def test_render_visibility_summary_includes_recent_outcomes():
    with orch._registry_lock:
        running = orch._blank_record()
        running["status"] = "scanning"
        completed = orch._blank_record()
        completed["terminal"] = True
        completed["results"] = [{"ok": True, "summary": "found tests"}]
        orch._registry["a1"] = running
        orch._registry["b2"] = completed
        orch._recent_terminal_events.append(
            {"agent_id": "b2", "outcome": "ok", "summary": "found tests"}
        )
    summary = orch.render_visibility_summary()
    assert "running 1" in summary
    assert "done 1" in summary
    assert "failed 0" in summary
    assert "a1: scanning" in summary
    assert "✓ b2 found tests" in summary


def test_render_visibility_summary_tracks_failed_recent_outcomes():
    with orch._registry_lock:
        failed = orch._blank_record()
        failed["terminal"] = True
        failed["error"] = {"message": "kaboom"}
        orch._registry["bad1"] = failed
        orch._recent_terminal_events.append(
            {"agent_id": "bad1", "outcome": "failed", "summary": "kaboom"}
        )
    summary = orch.render_visibility_summary()
    assert "running 0" in summary
    assert "failed 1" in summary
    assert "✗ bad1 kaboom" in summary


def test_note_followup_sent_marks_record_running():
    orch.note_spawn("persist1")
    orch.note_spawn_lifecycle("persist1", persistent=True)
    with orch._registry_lock:
        orch._registry["persist1"]["terminal"] = True
        orch._registry["persist1"]["results"] = [{"ok": True, "summary": "done"}]
    orch.note_followup_sent("persist1")
    rec = orch.agent_record("persist1")
    assert rec["persistent"] is True
    assert rec["followup_pending"] is True
    assert rec["terminal"] is False
    assert orch._classify_record(rec) == "running"


def test_should_idle_reap_only_persistent_terminal_idle_sessions():
    now = time.monotonic()
    rec = orch._blank_record()
    rec["persistent"] = True
    rec["terminal"] = True
    rec["last_frame"] = now - 1.0
    rec["last_activity"] = now - 500.0
    assert orch.should_idle_reap(rec, now, heartbeat_timeout=45.0, idle_timeout=300.0) is True

    rec["followup_pending"] = True
    assert orch.should_idle_reap(rec, now, heartbeat_timeout=45.0, idle_timeout=300.0) is False

    rec["followup_pending"] = False
    rec["persistent"] = False
    assert orch.should_idle_reap(rec, now, heartbeat_timeout=45.0, idle_timeout=300.0) is False


def test_clean_exit_not_dirty():
    path = orch.ensure_started()
    r = AgentReporter(path, "tidy")
    r.connect()
    r.result(ok=True, summary="ok")
    r.close(0)
    assert _wait(lambda: (orch.agent_record("tidy") or {}).get("terminal"))
    # Give the disconnect callback a moment.
    _wait(lambda: orch.agent_record("tidy") is not None)
    rec = orch.agent_record("tidy")
    assert rec["terminal"] is True
    assert rec["dirty"] is False
