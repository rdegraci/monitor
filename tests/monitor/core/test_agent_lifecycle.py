"""Phase 8f lifecycle: agent_create persistent passthrough + one-shot helpers."""

import pytest

from monitor import config
from monitor.core import agent_tools
from monitor.core import conversation
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
        def create_interactive_subagent(
            self,
            prompt,
            persistent=False,
            write_access=False,
            write_scope="",
        ):
            calls.append((persistent, write_access, write_scope))
            return {"session_name": f"s{len(calls)}", "meta_path": None, "log_path": None}

    monkeypatch.setattr(agent_tools, "_SCREEN", FakeScreen())
    assert agent_tools.agent_create("x")["status"] == "ok"
    assert agent_tools.agent_create("y", persistent=True)["status"] == "ok"
    assert calls == [(False, False, ""), (True, False, "")]


def test_agent_create_passes_delegated_write_grant(monkeypatch):
    monkeypatch.setenv("MONITOR_ENABLE_AGENT_ORCHESTRATION", "1")
    monkeypatch.setenv("MONITOR_AGENT_MAX_BREADTH", "10")
    monkeypatch.setenv("MONITOR_AGENT_MAX_TOTAL", "10")

    calls = []

    class FakeScreen:
        def create_interactive_subagent(
            self,
            prompt,
            persistent=False,
            write_access=False,
            write_scope="",
        ):
            calls.append((persistent, write_access, write_scope))
            return {"session_name": "s1", "meta_path": None, "log_path": None}

    monkeypatch.setattr(agent_tools, "_SCREEN", FakeScreen())

    out = agent_tools.agent_create(
        "edit files",
        write_access=True,
        write_scope="src/foo.py\ntests/foo_test.py",
    )

    assert out["status"] == "ok"
    assert calls == [(False, True, "src/foo.py\ntests/foo_test.py")]


def test_agent_create_rejects_write_scope_without_write_access(monkeypatch):
    monkeypatch.setenv("MONITOR_ENABLE_AGENT_ORCHESTRATION", "1")

    out = agent_tools.agent_create(
        "edit files",
        write_access=False,
        write_scope="src/foo.py",
    )

    assert out["status"] == "error"
    assert out["message"] == "write_scope requires write_access=true"


def test_agent_create_rejects_non_bool_write_access(monkeypatch):
    monkeypatch.setenv("MONITOR_ENABLE_AGENT_ORCHESTRATION", "1")

    out = agent_tools.agent_create(
        "edit files",
        write_access="yes",
    )

    assert out["status"] == "error"
    assert out["message"] == "write_access must be a bool"


def test_agent_create_rejects_non_string_write_scope(monkeypatch):
    monkeypatch.setenv("MONITOR_ENABLE_AGENT_ORCHESTRATION", "1")

    out = agent_tools.agent_create(
        "edit files",
        write_access=True,
        write_scope=None,
    )

    assert out["status"] == "error"
    assert out["message"] == "write_scope must be a str"


def test_maybe_report_returns_bool(monkeypatch):
    path = orch.ensure_started()
    reporter = AgentReporter(path, "rb")
    reporter.connect()
    agent_reporter.set_active(reporter)
    monkeypatch.setattr(
        config,
        "CONVERSATION_HISTORY",
        [{"role": "assistant", "content": "the answer"}],
        raising=False,
    )
    assert conversation._maybe_report_agent_result("do x") is True
    assert conversation._maybe_report_agent_result("   ") is False
    agent_reporter.set_active(None)
    assert conversation._maybe_report_agent_result("do x") is False
    reporter.close()


def test_agent_is_one_shot():
    assert conversation._agent_is_one_shot() is False
    agent_reporter.set_active(AgentReporter("/nope.sock", "a", one_shot=True))
    assert conversation._agent_is_one_shot() is True
    agent_reporter.set_active(AgentReporter("/nope.sock", "b", one_shot=False))
    assert conversation._agent_is_one_shot() is False
