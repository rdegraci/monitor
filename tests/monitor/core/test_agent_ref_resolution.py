"""agent_logfile / agent_kill / agent_send accept the session_name returned by
agent_create (the bug: they used to demand a positional integer index, so the
LLM jammed the session-name digits into it → 'Invalid session index')."""

import pytest

from monitor.core import agent_tools
from monitor.lib import subagent_logging


class FakeScreen:
    def __init__(self, names):
        self._names = list(names)
        self.killed = []
        self.sent = []

    def load_sessions_index(self):
        return [{"session_name": n} for n in self._names]

    def get_session_by_index(self, i):
        if 1 <= i <= len(self._names):
            return {"session_name": self._names[i - 1]}
        raise Exception(f"Invalid session index: {i}")

    def kill_session(self, name):
        self.killed.append(name)
        return True

    def send_to_session(self, name, text):
        self.sent.append((name, text))
        return True


def test_resolve_by_name_and_index(monkeypatch):
    monkeypatch.setattr(agent_tools, "_SCREEN", FakeScreen(["20260605_ady"]))
    assert agent_tools._resolve_agent_ref("20260605_ady") == "20260605_ady"  # by name
    assert agent_tools._resolve_agent_ref("1") == "20260605_ady"             # by 1-based index
    assert agent_tools._resolve_agent_ref(1) == "20260605_ady"               # int index
    assert agent_tools._resolve_agent_ref("20260605") is None  # the old bad numeric → not found
    assert agent_tools._resolve_agent_ref("nope") is None      # unknown name


def test_agent_logfile_by_session_name(monkeypatch):
    monkeypatch.setattr(agent_tools, "_SCREEN", FakeScreen(["s_log"]))
    monkeypatch.setattr(subagent_logging, "find_logfile_for_session_name", lambda n: f"/logs/{n}.log")
    res = agent_tools.agent_logfile("s_log")
    assert res["status"] == "ok"
    assert res["session"] == "s_log"
    assert res["logfile"] == "/logs/s_log.log"


def test_agent_kill_by_session_name(monkeypatch):
    fake = FakeScreen(["s_kill"])
    monkeypatch.setattr(agent_tools, "_SCREEN", fake)
    res = agent_tools.agent_kill("s_kill")
    assert res["status"] == "ok" and res["session"] == "s_kill" and res["killed"] is True
    assert fake.killed == ["s_kill"]


def test_agent_send_by_session_name(monkeypatch):
    monkeypatch.setenv("MONITOR_ENABLE_AGENT_ORCHESTRATION", "1")
    fake = FakeScreen(["s_send"])
    monkeypatch.setattr(agent_tools, "_SCREEN", fake)
    res = agent_tools.agent_send("s_send", "follow-up question")
    assert res["status"] == "ok" and res["session"] == "s_send" and res["sent"] is True
    assert fake.sent == [("s_send", "follow-up question")]


def test_unknown_session_is_clear_error(monkeypatch):
    monkeypatch.setattr(agent_tools, "_SCREEN", FakeScreen([]))
    res = agent_tools.agent_kill("ghost")
    assert res["status"] == "error"
    assert "No such agent session" in res["message"]
