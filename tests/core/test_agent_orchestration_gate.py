"""Tests for orchestration gating of agent tools.

These tests verify that agent_create and agent_send refuse to operate when
MONITOR_ENABLE_AGENT_ORCHESTRATION is disabled in config, and that they
succeed when enabled (with ScreenHandler mocked to avoid spawning real
subagents).
"""

from monitor.core import agent_tools
from monitor import config


def test_agent_create_disabled(monkeypatch):
    """agent_create returns an error when orchestration is disabled.

    The test sets MONITOR_ENABLE_AGENT_ORCHESTRATION to False and ensures the
    returned dictionary contains status 'error' and guidance to enable the
    feature.
    """
    monkeypatch.setattr(config, "MONITOR_ENABLE_AGENT_ORCHESTRATION", False)

    res = agent_tools.agent_create("Explain gravity")

    assert isinstance(res, dict)
    assert res.get("status") == "error"
    assert "MONITOR_ENABLE_AGENT_ORCHESTRATION" in res.get("message", "")


def test_agent_send_disabled(monkeypatch):
    """agent_send returns an error when orchestration is disabled.

    Sets the orchestration flag to False and verifies a structured error is returned.
    """
    monkeypatch.setattr(config, "MONITOR_ENABLE_AGENT_ORCHESTRATION", False)

    res = agent_tools.agent_send(0, "Hello")

    assert isinstance(res, dict)
    assert res.get("status") == "error"
    assert "MONITOR_ENABLE_AGENT_ORCHESTRATION" in res.get("message", "")


def test_agent_create_enabled(monkeypatch):
    """When enabled, agent_create delegates to the ScreenHandler (mocked).

    We patch the LazyScreen.create_interactive_subagent to return a predictable
    dict and verify agent_create returns an OK status with the expected
    session_name.
    """
    monkeypatch.setattr(config, "MONITOR_ENABLE_AGENT_ORCHESTRATION", True)

    class DummyScreen:
        def create_interactive_subagent(self, prompt):
            return {"session_name": "sess-123", "meta_path": "/tmp/meta", "log_path": "/tmp/log"}

    # Patch the module-level _SCREEN proxy to return our dummy screen
    monkeypatch.setattr(agent_tools, "_SCREEN", DummyScreen())

    res = agent_tools.agent_create("Why is the sky blue?")

    assert isinstance(res, dict)
    assert res.get("status") == "ok"
    assert res.get("session_name") == "sess-123"


def test_agent_send_enabled(monkeypatch):
    """When enabled, agent_send resolves the session and sends text (mocked).

    We patch get_session_by_index and send_to_session to simulate a working
    ScreenHandler.
    """
    monkeypatch.setattr(config, "MONITOR_ENABLE_AGENT_ORCHESTRATION", True)

    class DummyScreen:
        def get_session_by_index(self, index):
            return "sess-123"

        def send_to_session(self, session_name, text):
            return True

    monkeypatch.setattr(agent_tools, "_SCREEN", DummyScreen())

    res = agent_tools.agent_send(0, "Test message")

    assert isinstance(res, dict)
    assert res.get("status") == "ok"
    assert res.get("sent") is True
