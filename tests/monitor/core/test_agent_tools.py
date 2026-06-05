import pytest
from unittest.mock import patch, MagicMock

import monitor.config as config

from monitor.core.agent_tools import agent_create
from monitor.lib.screen_handler import SubagentCreationBlocked
from monitor.lib import agent_orchestrator as _orch


@pytest.fixture(autouse=True)
def _reset_orch():
    # Reset spawn counters so the default breadth/total cap (1) doesn't bleed
    # across these single-create tests.
    _orch.reset_for_test()
    yield
    _orch.reset_for_test()


@patch("monitor.core.agent_tools._SCREEN")
def test_agent_create_blocked(mock_screen, monkeypatch):
    monkeypatch.setattr(config, "MONITOR_ENABLE_AGENT_ORCHESTRATION", True)
    # Simulate handler raising SubagentCreationBlocked
    def raise_block(prompt, persistent=False):
        raise SubagentCreationBlocked("Sub-agent creation disabled: MONITOR_AGENT_MAX_DEPTH reached (depth=1, max=1).")
    mock_screen.create_interactive_subagent.side_effect = raise_block

    res = agent_create("hello")
    assert isinstance(res, dict)
    assert res.get("status") == "error"
    assert "MONITOR_AGENT_MAX_DEPTH" in res.get("message", "")


@patch("monitor.core.agent_tools._SCREEN")
def test_agent_create_success(mock_screen, monkeypatch):
    monkeypatch.setattr(config, "MONITOR_ENABLE_AGENT_ORCHESTRATION", True)
    # Simulate successful creation returning dict
    mock_screen.create_interactive_subagent.return_value = {
        "session_name": "20261003_abc",
        "meta_path": "/tmp/meta.json",
        "log_path": "/tmp/log"
    }
    res = agent_create("start agent")
    assert isinstance(res, dict)
    assert res.get("status") == "ok"
    assert res.get("session_name") == "20261003_abc"
