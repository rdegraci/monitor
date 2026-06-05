"""The agent caps follow the standard precedence: code default → config.yaml →
env override. Verifies the new keys are wired into config the same way the
depth keys are.
"""

import pytest

from monitor import config
from monitor.core.agent_tools import _agent_caps
from monitor.lib import agent_orchestrator as orch


def test_code_defaults_are_safe():
    # Module-level defaults (before any YAML) are maximally conservative.
    assert config.MONITOR_ENABLE_AGENT_ORCHESTRATION is False
    assert config.MONITOR_AGENT_MAX_DEPTH == 1
    assert config.MONITOR_AGENT_MAX_BREADTH == 1
    assert config.MONITOR_AGENT_MAX_TOTAL == 1
    assert config.MONITOR_AGENT_HEARTBEAT_TIMEOUT == 45


def test_caps_read_from_config_when_env_absent(monkeypatch):
    monkeypatch.delenv("MONITOR_AGENT_MAX_BREADTH", raising=False)
    monkeypatch.delenv("MONITOR_AGENT_MAX_TOTAL", raising=False)
    # Simulate a config.yaml that raised the caps.
    monkeypatch.setattr(config, "MONITOR_AGENT_MAX_BREADTH", 4, raising=False)
    monkeypatch.setattr(config, "MONITOR_AGENT_MAX_TOTAL", 10, raising=False)
    breadth, total = _agent_caps()
    assert breadth == 4
    assert total == 10


def test_env_overrides_config(monkeypatch):
    monkeypatch.setattr(config, "MONITOR_AGENT_MAX_BREADTH", 4, raising=False)
    monkeypatch.setenv("MONITOR_AGENT_MAX_BREADTH", "2")  # env wins
    breadth, _total = _agent_caps()
    assert breadth == 2


def test_heartbeat_timeout_reads_config(monkeypatch):
    monkeypatch.delenv("MONITOR_AGENT_HEARTBEAT_TIMEOUT", raising=False)
    monkeypatch.setattr(config, "MONITOR_AGENT_HEARTBEAT_TIMEOUT", 7.5, raising=False)
    assert orch._hb_timeout() == 7.5
    # env still wins
    monkeypatch.setenv("MONITOR_AGENT_HEARTBEAT_TIMEOUT", "3")
    assert orch._hb_timeout() == 3.0
