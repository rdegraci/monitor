"""Tests for Phase 8a async result harvest: completed/failed background agents
inject a notice into the orchestrator's NEXT turn (no blocking), via
agent_orchestrator._pending_injections → config.enqueue_next_llm_prefix.
"""

import time

import pytest

from monitor import config
from monitor.core import conversation
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
def _clean(monkeypatch):
    orch.reset_for_test()
    monkeypatch.setattr(config, "PENDING_LLM_PREFIXES", [], raising=False)
    yield
    orch.reset_for_test()


# --- injection queued on terminal frames ------------------------------------

def test_result_injection_content_and_dedup():
    path = orch.ensure_started()
    r = AgentReporter(path, "res2"); r.connect()
    r.result(ok=True, summary="did the thing")
    assert _wait(lambda: (orch.agent_record("res2") or {}).get("_injected"))
    drained = orch.drain_pending_injections()
    assert len(drained) == 1
    assert "res2" in drained[0] and "finished" in drained[0] and "did the thing" in drained[0]
    # Drain is destructive; a subsequent exit frame must NOT re-inject.
    r.close()
    time.sleep(0.1)
    assert orch.drain_pending_injections() == []


def test_error_injection():
    path = orch.ensure_started()
    r = AgentReporter(path, "err"); r.connect()
    r.report_error(kind="ValueError", message="kaboom")
    assert _wait(lambda: (orch.agent_record("err") or {}).get("_injected"))
    drained = orch.drain_pending_injections()
    assert "err" in drained[0] and "FAILED" in drained[0] and "kaboom" in drained[0]
    r.close()


def test_crash_injects_failure():
    path = orch.ensure_started()
    r = AgentReporter(path, "crash"); r.connect()
    r.status("working")
    r._sock.close()  # dirty disconnect, no result
    assert _wait(lambda: (orch.agent_record("crash") or {}).get("_injected"))
    drained = orch.drain_pending_injections()
    assert "crash" in drained[0] and "FAILED" in drained[0]


def test_clean_exit_without_result_does_not_inject():
    path = orch.ensure_started()
    r = AgentReporter(path, "quiet"); r.connect()
    r.close()  # exit frame, never sent a result
    assert _wait(lambda: (orch.agent_record("quiet") or {}).get("terminal"))
    time.sleep(0.1)
    assert orch.drain_pending_injections() == []


# --- main-thread fold into the prefix queue (rides the next LLM request) -----

def test_injection_folds_into_pending_prefixes():
    path = orch.ensure_started()
    r = AgentReporter(path, "inj"); r.connect()
    r.result(ok=True, summary="background finding")
    assert _wait(lambda: (orch.agent_record("inj") or {}).get("_injected"))

    # Main-thread fold (what prepare_query_context calls before draining prefixes).
    conversation._fold_agent_injections_into_prefixes()

    # Drained from the orchestrator and now queued as an LLM prefix for next turn.
    assert orch.drain_pending_injections() == []
    assert any("inj" in p and "background finding" in p for p in config.PENDING_LLM_PREFIXES)
    r.close()


def test_fold_is_noop_with_no_completed_agents():
    orch.ensure_started()
    conversation._fold_agent_injections_into_prefixes()
    assert config.PENDING_LLM_PREFIXES == []
