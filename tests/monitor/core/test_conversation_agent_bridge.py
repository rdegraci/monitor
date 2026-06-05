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
    yield
    orch.reset_for_test()


def test_no_agents_is_plain_prompt():
    s = _FakeSession("hello")
    out = conversation._prompt_with_agent_bridge(s, "PROMPT>")
    assert out == "hello"
    assert len(s.calls) == 1
    text, kwargs = s.calls[0]
    assert text == "PROMPT>"
    assert "bottom_toolbar" not in kwargs  # no toolbar when no agents


def test_active_agent_adds_toolbar(capsys):
    path = orch.ensure_started()
    r = AgentReporter(path, "ag")
    r.connect()
    r.status("indexing")
    assert _wait(lambda: orch.has_active_agents())

    s = _FakeSession("x")
    out = conversation._prompt_with_agent_bridge(s, "PROMPT>")
    assert out == "x"
    text, kwargs = s.calls[-1]
    assert "bottom_toolbar" in kwargs
    assert callable(kwargs["bottom_toolbar"])
    assert kwargs["bottom_toolbar"]()  # renders non-empty while active
    r.close()


def test_toolbar_returns_none_when_empty(capsys):
    """The bottom_toolbar callable returns None (not '') when there's no active
    status, so prompt_toolkit doesn't leave a blank bar."""
    # No agents → render_toolbar() is "" → callable should yield None.
    path = orch.ensure_started()
    r = AgentReporter(path, "tb"); r.connect(); r.status("scanning")
    assert _wait(lambda: orch.has_active_agents())

    captured = {}

    class FakeSession:
        def prompt(self, text, **kwargs):
            captured["toolbar"] = kwargs.get("bottom_toolbar")
            return "x"

    conversation._prompt_with_agent_bridge(FakeSession(), "P>")
    tb = captured["toolbar"]
    assert callable(tb)
    assert tb()  # non-empty while active
    # After the agent finishes, the callable yields None (not a blank string).
    r.result(ok=True, summary="done"); r.close()
    assert _wait(lambda: not orch.has_active_agents())
    assert tb() is None


def test_pending_output_flushed_above_prompt(capsys):
    path = orch.ensure_started()
    r = AgentReporter(path, "ag2")
    r.connect()
    r.emit_stdout("agent says hi")
    r.result(ok=True, summary="finished")
    assert _wait(lambda: (orch.agent_record("ag2") or {}).get("terminal"))

    s = _FakeSession("x")
    conversation._prompt_with_agent_bridge(s, "PROMPT>")
    printed = capsys.readouterr().out
    assert "agent says hi" in printed
    assert "✓ finished" in printed
    r.close()
