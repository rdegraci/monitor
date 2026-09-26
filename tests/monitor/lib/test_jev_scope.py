"""Tests for Jev material scope-growth pause."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from monitor.lib import jev_scope as js


@pytest.fixture(autouse=True)
def _clear_jev_env(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("MONITOR_JEV", raising=False)
    monkeypatch.delenv("MONITOR_JEV_CONFIDENCE", raising=False)


def test_scope_disabled_no_pause():
    assert js.should_pause_for_scope("rewrite the auth system", material=True) is None


@patch("monitor.lib.jev_scope.tc.system_one")
def test_scope_pause_on_high_noul(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    monkeypatch.setenv("MONITOR_JEV_CONFIDENCE", "0.6")
    mock_system_one.return_value = {
        "answers": {"is_material_scope_growth": {"type": "noul", "noul": 0.9}}
    }
    notice = js.should_pause_for_scope(
        "Also migrate the entire billing subsystem", material=True
    )
    assert notice is not None
    assert "jev_scope" in notice


@patch("monitor.lib.jev_scope.tc.system_one")
def test_scope_skip_short_non_material(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    assert js.should_pause_for_scope("typo fix", material=False) is None
    mock_system_one.assert_not_called()
