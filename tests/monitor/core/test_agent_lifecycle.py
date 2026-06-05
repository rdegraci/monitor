"""Phase 8f lifecycle: agent_create persistent passthrough + one-shot helpers."""

import pytest

from monitor import config
from monitor.core import conversation
from monitor.core import agent_tools
from monitor.lib import agent_orchestrator as orch
from monitor.lib import agent_reporter
from monitor.lib.agent_reporter import AgentReporter


@pytest.fixture(autouse=True)
def _clean():
    orch.reset_for_test()
    agent_reporter.set_active(None)
    yield
    agent_reporter.set_active(None)
    orch.reset_for_test()


def test_agent_create_passes_persistent(monkeypatch):
    monkeypatch.setenv("MONITOR_ENABLE_AGENT_ORCHESTRATION", "1")
    monkeypatch.setenv("MONITOR_AGENT_MAX_BREADTH", "10")
    monkeypatch.setenv("MONITOR_AGENT_MAX_TOTAL", "10")

    calls = []

    class FakeScreen:
        def create_interactive_subagent(self, prompt, persistent=False):
            calls.append(persistent)
            return {"session_name": f"s{len(calls)}", "meta_path": None, "log_path": None}

    monkeypatch.setattr(agent_tools, "_SCREEN", FakeScreen())
    assert agent_tools.agent_create("x")["status"] == "ok"            # default
    assert agent_tools.agent_create("y", persistent=True)["status"] == "ok"
    assert calls == [False, True]  # one-shot by default, persistent when asked


def test_maybe_report_returns_bool(monkeypatch):
    path = orch.ensure_started()
    r = AgentReporter(path, "rb"); r.connect()
    agent_reporter.set_active(r)
    monkeypatch.setattr(config, "CONVERSATION_HISTORY",
                        [{"role": "assistant", "content": "the answer"}], raising=False)
    assert conversation._maybe_report_agent_result("do x") is True
    assert conversation._maybe_report_agent_result("   ") is False  # empty input
    agent_reporter.set_active(None)
    assert conversation._maybe_report_agent_result("do x") is False  # no reporter
    r.close()


def test_agent_is_one_shot():
    assert conversation._agent_is_one_shot() is False  # no active reporter
    agent_reporter.set_active(AgentReporter("/nope.sock", "a", one_shot=True))
    assert conversation._agent_is_one_shot() is True
    agent_reporter.set_active(AgentReporter("/nope.sock", "b", one_shot=False))
    assert conversation._agent_is_one_shot() is False
