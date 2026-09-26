"""Tests for Final Jev helpers (affirmative, harvest, review, memory, compact)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from monitor.lib import jev_affirmative as ja
from monitor.lib import jev_agent_harvest as jh
from monitor.lib import jev_compact as jc
from monitor.lib import jev_memory as jm
from monitor.lib import jev_review_gate as jrev


@pytest.fixture(autouse=True)
def _clear_jev_env(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("MONITOR_JEV", raising=False)
    monkeypatch.delenv("MONITOR_JEV_CONFIDENCE", raising=False)


def test_affirmative_heuristics():
    assert ja.looks_like_offer("Would you like me to apply the patch?")
    assert ja.looks_like_short_affirmative("yes")
    assert not ja.looks_like_short_affirmative("yes but change the API too")


def test_affirmative_disabled_no_gate():
    assert (
        ja.maybe_gate_affirmative(
            "yes", "Would you like me to proceed with the refactor?"
        )
        is None
    )


@patch("monitor.lib.jev_affirmative.tc.system_one")
def test_affirmative_ask(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    mock_system_one.return_value = {
        "answers": {
            "affirmative": {"type": "choice", "choice": "ask", "confidence": 0.9}
        }
    }
    msg = ja.maybe_gate_affirmative(
        "ok", "If you want, I can rewrite the module next."
    )
    assert msg is not None
    assert "ambiguous" in msg.lower() or "ask" in msg.lower()


@patch("monitor.lib.jev_agent_harvest.tc.system_one")
def test_harvest_annotates(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    mock_system_one.return_value = {
        "answers": {
            "harvest_status": {
                "type": "choice",
                "choice": "done",
                "confidence": 0.95,
            },
            "finding_quality": {
                "type": "score",
                "score": 2.0,
                "confidence": 0.9,
            },
        }
    }
    out = jh.annotate_injection("Background sub-agent 'a1' finished: found bug")
    assert out.startswith("[jev_harvest")
    assert "done" in out


@patch("monitor.lib.jev_review_gate.tc.system_one")
def test_review_gate_ship(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    mock_system_one.return_value = {
        "answers": {
            "ship_decision": {
                "type": "choice",
                "choice": "ship",
                "confidence": 0.9,
            },
            "correctness": {"type": "score", "score": 3.0, "confidence": 0.9},
            "risk": {"type": "score", "score": 0.0, "confidence": 0.9},
            "test_gaps": {"type": "score", "score": 0.0, "confidence": 0.9},
        }
    }
    d = jrev.decide_review_gate("diff --git a/x b/x\n+ok")
    assert d.acted is True
    assert d.route == "ship"
    assert d.message is not None


def test_memory_disabled_allows():
    assert jm.should_attempt_remember("remember my favorite editor is vim") is True


@patch("monitor.lib.jev_memory.tc.system_one")
def test_memory_low_noul_skips(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    mock_system_one.return_value = {
        "answers": {"should_remember": {"type": "noul", "noul": 0.05}}
    }
    assert jm.should_attempt_remember("what time is it?") is False


@patch("monitor.lib.jev_compact.tc.system_one")
def test_compact_defers(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    mock_system_one.return_value = {
        "answers": {"summarize_now": {"type": "noul", "noul": 0.1}}
    }
    assert (
        jc.should_soft_summarize_now(tokens_in_history=9000, max_tokens=10000)
        is False
    )
