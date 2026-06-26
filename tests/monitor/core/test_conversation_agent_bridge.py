import monitor.config as config

"""Tests for the Phase 3 terminal bridge in get_input (_prompt_with_agent_bridge).

Verifies the gating guarantee: with NO active agents the helper behaves exactly
like a plain session.prompt(...), and with active agents it flushes buffered
output and adds a bottom_toolbar. Uses a fake session (no real prompt_toolkit
event loop).
"""

import time

import pytest

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


class _FakeSession:
    def __init__(self, ret="typed"):
        self.ret = ret
        self.calls = []

    def prompt(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return self.ret


@pytest.fixture(autouse=True)
def _clean():
    orch.reset_for_test()
    conversation._LAST_AGENT_VISIBILITY_SUMMARY = None
    yield
    conversation._LAST_AGENT_VISIBILITY_SUMMARY = None
    orch.reset_for_test()


def test_no_agents_is_plain_prompt():
    s = _FakeSession("hello")
    out = conversation._prompt_with_agent_bridge(s, "PROMPT>")
    assert out == "hello"
    assert len(s.calls) == 1
    text, kwargs = s.calls[0]
    assert text == "PROMPT>"
    assert "bottom_toolbar" not in kwargs  # no toolbar when no agents


def test_active_agent_adds_toolbar(monkeypatch):
    monkeypatch.setattr(orch, "drain_pending_output", lambda limit=None: [])
    monkeypatch.setattr(orch, "has_active_agents", lambda: True)
    monkeypatch.setattr(
        orch,
        "render_visibility_summary",
        lambda: "agents — running 1 | active ag: indexing",
    )
    monkeypatch.setattr(
        orch,
        "render_toolbar",
        lambda: "agents — running 1 | active ag: indexing",
    )
    s = _FakeSession("x")
    out = conversation._prompt_with_agent_bridge(s, "PROMPT>")
    assert out == "x"
    text, kwargs = s.calls[-1]
    assert "bottom_toolbar" in kwargs
    assert callable(kwargs["bottom_toolbar"])
    assert kwargs["bottom_toolbar"]()  # renders non-empty while active
    assert "running 1" in kwargs["bottom_toolbar"]()


def test_toolbar_returns_none_when_empty(monkeypatch):
    """The bottom_toolbar callable returns None (not '') when there's no active
    status, so prompt_toolkit doesn't leave a blank bar."""
    captured = {}

    class FakeSession:
        def prompt(self, text, **kwargs):
            captured["toolbar"] = kwargs.get("bottom_toolbar")
            return "x"

    state = {"active": True}
    monkeypatch.setattr(orch, "drain_pending_output", lambda limit=None: [])
    monkeypatch.setattr(orch, "has_active_agents", lambda: state["active"])
    monkeypatch.setattr(
        orch,
        "render_visibility_summary",
        lambda: "agents — running 1 | active tb: scanning" if state["active"] else "",
    )
    monkeypatch.setattr(
        orch,
        "render_toolbar",
        lambda: "agents — running 1 | active tb: scanning" if state["active"] else "",
    )
    conversation._prompt_with_agent_bridge(FakeSession(), "P>")
    tb = captured["toolbar"]
    assert callable(tb)
    assert tb()  # non-empty while active
    # After the agent finishes, the callable yields None (not a blank string).
    state["active"] = False
    assert tb() is None


def test_pending_output_flushed_above_prompt(capsys, monkeypatch):
    monkeypatch.setattr(
        orch,
        "drain_pending_output",
        lambda limit=None: ["[ag2] agent says hi", "[ag2] ✓ finished"],
    )
    monkeypatch.setattr(orch, "drain_pending_injections", lambda: [])
    monkeypatch.setattr(orch, "has_active_agents", lambda: False)
    s = _FakeSession("x")
    conversation._prompt_with_agent_bridge(s, "PROMPT>")
    printed = capsys.readouterr().out
    assert "agent says hi" in printed
    assert "✓ finished" in printed


def test_collation_turn_suppresses_terminal_result_replay(capsys, monkeypatch):
    monkeypatch.setattr(config, "CURRENT_TURN_IS_COLLATION", False, raising=False)
    monkeypatch.setattr(config, "PENDING_LLM_PREFIXES", [], raising=False)
    monkeypatch.setattr(
        orch,
        "drain_pending_output",
        lambda limit=None: ["[ag2] tool: reading file", "[ag2] ✓ finished"],
    )
    monkeypatch.setattr(
        orch,
        "drain_pending_injections",
        lambda: ["Background sub-agent 'ag2' finished: finished"],
    )
    monkeypatch.setattr(orch, "has_active_agents", lambda: False)
    s = _FakeSession("x")
    conversation._prompt_with_agent_bridge(s, "PROMPT>")
    printed = capsys.readouterr().out
    assert "tool: reading file" in printed
    assert "✓ finished" not in printed
    assert config.CURRENT_TURN_IS_COLLATION is True
    assert any("ag2" in prefix for prefix in config.PENDING_LLM_PREFIXES)


def test_active_agent_summary_prints_once_until_it_changes(capsys, monkeypatch):
    summary = {"value": "agents — running 1 | active ag3: indexing"}

    def _render_summary():
        return summary["value"]

    monkeypatch.setattr(orch, "drain_pending_output", lambda limit=None: [])
    monkeypatch.setattr(orch, "has_active_agents", lambda: True)
    monkeypatch.setattr(orch, "render_visibility_summary", _render_summary)

    s = _FakeSession("x")
    conversation._prompt_with_agent_bridge(s, "PROMPT>")
    first = capsys.readouterr().out
    assert "agents — running 1" in first
    assert "ag3: indexing" in first

    conversation._prompt_with_agent_bridge(s, "PROMPT>")
    second = capsys.readouterr().out
    assert "agents — running 1" not in second

    summary["value"] = "agents — running 1 | active ag3: verifying"
    conversation._prompt_with_agent_bridge(s, "PROMPT>")
    third = capsys.readouterr().out
    assert "agents — running 1" in third
    assert "ag3: verifying" in third
