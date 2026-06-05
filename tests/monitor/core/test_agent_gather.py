"""Tests for agent_gather — the Phase 8 LLM orchestration keystone.

Drives the orchestrator registry with real AgentReporters (no subprocess) and
asserts the partial-failure-honest bucketing: every requested id lands in
exactly one of ok / failed / pending.
"""

import time

import pytest

from monitor.core.agent_tools import agent_gather
from monitor.lib import agent_orchestrator as orch
from monitor.lib.agent_reporter import AgentReporter


@pytest.fixture(autouse=True)
def _enable_and_clean(monkeypatch):
    monkeypatch.setenv("MONITOR_ENABLE_AGENT_ORCHESTRATION", "1")
    orch.reset_for_test()
    yield
    orch.reset_for_test()


def test_disabled_returns_error(monkeypatch):
    monkeypatch.setenv("MONITOR_ENABLE_AGENT_ORCHESTRATION", "0")
    out = agent_gather(["x"])
    assert out["status"] == "error"
    assert "disabled" in out["message"]


def test_gather_collects_results():
    path = orch.ensure_started()
    a = AgentReporter(path, "ag-a"); a.connect()
    b = AgentReporter(path, "ag-b"); b.connect()
    a.result(ok=True, summary="A done", data={"n": 1}); a.close()
    b.result(ok=True, summary="B done"); b.close()

    out = agent_gather(["ag-a", "ag-b"], timeout=5)
    assert out["status"] == "ok"
    assert out["requested"] == 2
    assert out["timed_out"] is False
    assert out["failed"] == [] and out["pending"] == []
    by_id = {e["id"]: e["result"] for e in out["ok"]}
    assert by_id["ag-a"]["summary"] == "A done"
    assert by_id["ag-a"]["data"] == {"n": 1}
    assert by_id["ag-b"]["summary"] == "B done"


def test_partial_failure_crash_is_reported_not_dropped():
    path = orch.ensure_started()
    good = AgentReporter(path, "good"); good.connect()
    crash = AgentReporter(path, "crash"); crash.connect()
    good.result(ok=True, summary="ok"); good.close()
    crash.status("working")
    crash._sock.close()  # crash WITHOUT a result/exit → dirty disconnect

    out = agent_gather(["good", "crash"], timeout=5)
    ok_ids = {e["id"] for e in out["ok"]}
    failed_ids = {e["id"] for e in out["failed"]}
    assert ok_ids == {"good"}
    assert failed_ids == {"crash"}
    assert "dirty disconnect" in out["failed"][0]["reason"]


def test_error_frame_goes_to_failed():
    path = orch.ensure_started()
    e = AgentReporter(path, "err"); e.connect()
    e.report_error(kind="ValueError", message="kaboom")
    e.close()
    out = agent_gather(["err"], timeout=5)
    assert out["ok"] == []
    assert out["failed"][0]["id"] == "err"
    assert "kaboom" in out["failed"][0]["reason"]


def test_never_connected_agent_is_failed():
    orch.ensure_started()
    out = agent_gather(["ghost"], timeout=1)
    assert out["failed"][0]["id"] == "ghost"
    assert "never connected" in out["failed"][0]["reason"]


def test_pending_on_timeout():
    path = orch.ensure_started()
    slow = AgentReporter(path, "slow"); slow.connect()
    slow.status("still going")  # never finishes
    start = time.monotonic()
    out = agent_gather(["slow"], timeout=0.5, poll_interval=0.05)
    elapsed = time.monotonic() - start
    assert out["timed_out"] is True
    assert out["pending"] == ["slow"]
    assert elapsed < 3  # honored the short timeout
    slow.close()


def test_single_id_string_accepted():
    path = orch.ensure_started()
    r = AgentReporter(path, "solo"); r.connect()
    r.result(ok=True, summary="solo done"); r.close()
    out = agent_gather("solo", timeout=5)  # bare string, not a list
    assert out["requested"] == 1
    assert out["ok"][0]["id"] == "solo"


def test_clean_exit_without_result_frame():
    path = orch.ensure_started()
    r = AgentReporter(path, "noresult"); r.connect()
    r.status("ran")
    r.close()  # exit frame, but never sent a result
    out = agent_gather("noresult", timeout=5)
    assert out["ok"][0]["id"] == "noresult"
    assert out["ok"][0]["result"]["no_result_frame"] is True


def test_empty_ids_error():
    out = agent_gather([])
    assert out["status"] == "error"
