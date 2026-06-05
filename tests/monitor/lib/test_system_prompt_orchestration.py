"""Phase 8g/8b: build_system_prompt appends orchestration guidance conditionally.

- normal session (orchestration off, not an agent) → neither block
- orchestrator (orchestration on, not an agent) → the "how to delegate" block
- sub-agent (--agent / config.AGENT) → the "you are a sub-agent" block
"""

import pytest

from monitor import config
from monitor.lib import system_prompt


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(config, "AGENT", False, raising=False)
    monkeypatch.setattr(config, "MONITOR_ENABLE_AGENT_ORCHESTRATION", False, raising=False)
    yield


def test_default_session_has_no_orchestration_guidance():
    sp = system_prompt.build_system_prompt()
    assert "Sub-agent orchestration" not in sp
    assert "You are a sub-agent" not in sp


def test_orchestrator_gets_delegation_guidance(monkeypatch):
    monkeypatch.setattr(config, "MONITOR_ENABLE_AGENT_ORCHESTRATION", True, raising=False)
    sp = system_prompt.build_system_prompt()
    assert "Sub-agent orchestration" in sp
    assert "agent_create" in sp
    assert "do NOT wait" in sp or "fire-and-continue" in sp
    # orchestrator is not itself a sub-agent
    assert "You are a sub-agent" not in sp


def test_subagent_gets_subagent_guidance(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    # even if orchestration is also enabled (inherited), the agent block wins
    monkeypatch.setattr(config, "MONITOR_ENABLE_AGENT_ORCHESTRATION", True, raising=False)
    sp = system_prompt.build_system_prompt()
    assert "You are a sub-agent" in sp
    assert "tight, structured summary" in sp
    # a sub-agent must not be told to delegate (it can't spawn)
    assert "Sub-agent orchestration" not in sp


def test_platform_template_always_present():
    sp = system_prompt.build_system_prompt()
    assert "coding assistant invoked from a CLI harness" in sp
