"""Tests for Phase 8b: a sub-agent emitting its turn result back to the
orchestrator via _maybe_report_agent_result, and the reporter singleton.
"""

import time

import pytest

from monitor import config
from monitor.core import conversation
from monitor.lib import agent_orchestrator as orch
from monitor.lib import agent_reporter
from monitor.lib.agent_reporter import AgentReporter


def _wait(predicate, timeout=2.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    orch.reset_for_test()
    agent_reporter.set_active(None)
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [], raising=False)
    yield
    agent_reporter.set_active(None)
    orch.reset_for_test()


def test_singleton_set_get():
    assert agent_reporter.active() is None
    r = AgentReporter("/nonexistent.sock", "x")
    agent_reporter.set_active(r)
    assert agent_reporter.active() is r
    agent_reporter.set_active(None)
    assert agent_reporter.active() is None


def test_reports_assistant_response_as_result():
    path = orch.ensure_started()
    rep = AgentReporter(path, "worker")
    assert rep.connect()
    agent_reporter.set_active(rep)

    config.CONVERSATION_HISTORY = [
        {"role": "user", "content": "do the thing"},
        {"role": "assistant", "content": "here is the answer"},
    ]
    conversation._maybe_report_agent_result("do the thing")

    assert _wait(lambda: (orch.agent_record("worker") or {}).get("results"))
    rec = orch.agent_record("worker")
    assert rec["results"][-1]["summary"] == "here is the answer"
    rep.close()


def test_noop_without_active_reporter():
    # No active reporter → must not raise and nothing recorded.
    orch.ensure_started()
    config.CONVERSATION_HISTORY = [{"role": "assistant", "content": "x"}]
    conversation._maybe_report_agent_result("input")
    assert orch.all_agent_ids() == []


def test_noop_on_empty_input():
    path = orch.ensure_started()
    rep = AgentReporter(path, "w2"); rep.connect()
    agent_reporter.set_active(rep)
    config.CONVERSATION_HISTORY = [{"role": "assistant", "content": "x"}]
    conversation._maybe_report_agent_result("   ")  # blank
    time.sleep(0.1)
    rec = orch.agent_record("w2")
    # connected (hello) but no result emitted for blank input
    assert (rec or {}).get("results") in (None, [])
    rep.close()


def test_noop_when_no_assistant_message():
    path = orch.ensure_started()
    rep = AgentReporter(path, "w3"); rep.connect()
    agent_reporter.set_active(rep)
    config.CONVERSATION_HISTORY = [{"role": "user", "content": "only a user msg"}]
    conversation._maybe_report_agent_result("input")
    time.sleep(0.1)
    rec = orch.agent_record("w3")
    assert (rec or {}).get("results") in (None, [])
    rep.close()


def test_end_to_end_gather_collects_reported_result():
    """The whole 8b→8a path: agent reports a turn result, gather returns it."""
    from monitor.core.agent_tools import agent_gather
    import os
    os.environ["MONITOR_ENABLE_AGENT_ORCHESTRATION"] = "1"
    try:
        path = orch.ensure_started()
        rep = AgentReporter(path, "e2e"); rep.connect()
        agent_reporter.set_active(rep)
        config.CONVERSATION_HISTORY = [{"role": "assistant", "content": "research finding"}]
        conversation._maybe_report_agent_result("go research")
        rep.close()  # clean exit after reporting

        out = agent_gather(["e2e"], timeout=5)
        assert out["ok"][0]["id"] == "e2e"
        assert out["ok"][0]["result"]["summary"] == "research finding"
    finally:
        os.environ.pop("MONITOR_ENABLE_AGENT_ORCHESTRATION", None)
