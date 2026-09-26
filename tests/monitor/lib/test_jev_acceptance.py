"""Tests for Jev acceptance done steer."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from monitor.lib import jev_acceptance as jacc


@pytest.fixture(autouse=True)
def _clear_jev_env(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("MONITOR_JEV", raising=False)
    monkeypatch.delenv("MONITOR_JEV_CONFIDENCE", raising=False)


def test_acceptance_disabled_allows():
    assert (
        jacc.maybe_steer_todo_done(
            {"item": "Ship feature", "notes": ""},
            acceptance_criteria=["tests pass"],
        )
        is None
    )


@patch("monitor.lib.jev_acceptance.tc.system_one")
def test_acceptance_low_noul_steers(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    monkeypatch.setenv("MONITOR_JEV_CONFIDENCE", "0.6")
    mock_system_one.return_value = {
        "answers": {"acceptance_met": {"type": "noul", "noul": 0.2}}
    }
    steer = jacc.maybe_steer_todo_done(
        {"item": "Add OAuth", "notes": "started"},
        acceptance_criteria=["OAuth works end-to-end"],
    )
    assert steer is not None
    assert "jev_acceptance" in steer


@patch("monitor.lib.jev_acceptance.tc.system_one")
def test_acceptance_high_noul_allows(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    monkeypatch.setenv("MONITOR_JEV_CONFIDENCE", "0.6")
    mock_system_one.return_value = {
        "answers": {"acceptance_met": {"type": "noul", "noul": 0.95}}
    }
    assert (
        jacc.maybe_steer_todo_done(
            {"item": "Add OAuth", "notes": "done and tested"},
            acceptance_criteria=["OAuth works"],
        )
        is None
    )
