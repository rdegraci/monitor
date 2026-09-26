"""Tests for Jev reasoning-bump Noul backstop."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from monitor.lib import jev_reasoning_bump as jrb


@pytest.fixture(autouse=True)
def _clear_jev_env(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("MONITOR_JEV", raising=False)
    monkeypatch.delenv("MONITOR_JEV_CONFIDENCE", raising=False)


def test_reasoning_bump_disabled_uses_heuristic():
    out = jrb.resolve_reasoning_bump(
        "Please find the bug in the auth flow",
        "low",
    )
    assert out is not None


@patch("monitor.lib.jev_reasoning_bump.tc.system_one")
def test_reasoning_bump_jev_confirms(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    monkeypatch.setenv("MONITOR_JEV_CONFIDENCE", "0.6")
    mock_system_one.return_value = {
        "answers": {"should_bump_reasoning": {"type": "noul", "noul": 0.9}}
    }
    out = jrb.resolve_reasoning_bump("find the bug in login", "low")
    assert out is not None


@patch("monitor.lib.jev_reasoning_bump.tc.system_one")
def test_reasoning_bump_jev_declines_heuristic(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    monkeypatch.setenv("MONITOR_JEV_CONFIDENCE", "0.6")
    mock_system_one.return_value = {
        "answers": {"should_bump_reasoning": {"type": "noul", "noul": 0.1}}
    }
    out = jrb.resolve_reasoning_bump("find the bug in login", "low")
    assert out is None


@patch("monitor.lib.jev_reasoning_bump.tc.system_one")
def test_reasoning_bump_mid_band_promotes(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    monkeypatch.setenv("MONITOR_JEV_CONFIDENCE", "0.6")
    mock_system_one.return_value = {
        "answers": {"should_bump_reasoning": {"type": "noul", "noul": 0.95}}
    }
    text = "x" * 250
    out = jrb.resolve_reasoning_bump(text, "low")
    assert out is not None
