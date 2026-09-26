"""Tests for Jev compaction summary fidelity."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from monitor.lib import jev_fidelity as jf


@pytest.fixture(autouse=True)
def _clear_jev_env(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("MONITOR_JEV", raising=False)
    monkeypatch.delenv("MONITOR_JEV_CONFIDENCE", raising=False)


def test_fidelity_disabled_accepts():
    assert jf.summary_is_faithful_enough("We fixed auth.py and tests pass.") is True


def test_fidelity_empty_rejects(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    assert jf.summary_is_faithful_enough("   ") is False


@patch("monitor.lib.jev_fidelity.tc.system_one")
def test_fidelity_low_score_rejects(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    monkeypatch.setenv("MONITOR_JEV_CONFIDENCE", "0.5")
    mock_system_one.return_value = {
        "answers": {
            "summary_fidelity": {"type": "score", "score": 0.5, "confidence": 0.9}
        }
    }
    assert jf.summary_is_faithful_enough("Did some stuff.") is False


@patch("monitor.lib.jev_fidelity.tc.system_one")
def test_fidelity_adequate_accepts(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    monkeypatch.setenv("MONITOR_JEV_CONFIDENCE", "0.5")
    mock_system_one.return_value = {
        "answers": {
            "summary_fidelity": {"type": "score", "score": 2.5, "confidence": 0.9}
        }
    }
    assert (
        jf.summary_is_faithful_enough(
            "Fixed auth.py OAuth flow; tests pass; acceptance criteria met."
        )
        is True
    )


def test_history_excerpt_for_fidelity():
    hist = [
        {"role": "system", "content": "ignore"},
        {"role": "user", "content": "fix the bug"},
        {"role": "assistant", "content": "looking at auth.py"},
    ]
    text = jf.history_excerpt_for_fidelity(hist)
    assert "fix the bug" in text
    assert "auth.py" in text
    assert "ignore" not in text
