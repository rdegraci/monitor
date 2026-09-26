"""Tests for monitor.lib.jev_tool_route and jev_reasoning."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from monitor.lib import jev_reasoning as jr
from monitor.lib import jev_tool_route as jt


@pytest.fixture(autouse=True)
def _clear_jev_env(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("MONITOR_JEV", raising=False)
    monkeypatch.delenv("MONITOR_JEV_CONFIDENCE", raising=False)


def test_tool_route_disabled():
    d = jt.decide_tool_group("search the docs somehow")
    assert d.acted is False
    assert d.reason == "jev_disabled"
    assert jt.maybe_jev_auto_widen_groups("x") == set()


@patch("monitor.lib.jev_tool_route.tc.system_one")
def test_tool_route_steers_network(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    mock_system_one.return_value = {
        "answers": {
            "tool_group": {
                "type": "choice",
                "choice": "network",
                "confidence": 0.92,
            }
        }
    }
    d = jt.decide_tool_group("look up the latest release notes online")
    assert d.acted is True
    assert d.group == jt.NETWORK_GROUP
    assert jt.maybe_jev_auto_widen_groups("look up online") == {jt.NETWORK_GROUP}


@patch("monitor.lib.jev_tool_route.tc.system_one")
def test_tool_route_none_acted(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    mock_system_one.return_value = {
        "answers": {
            "tool_group": {"type": "choice", "choice": "none", "confidence": 0.9}
        }
    }
    assert jt.maybe_jev_auto_widen_groups("hello") == set()


def test_escalate_disabled_allows():
    d = jr.decide_escalate_on_failure("Traceback (most recent call last)")
    assert d.acted is False
    assert jr.should_jev_allow_escalate("Traceback (most recent call last)") is True


@patch("monitor.lib.jev_reasoning.tc.system_one")
def test_escalate_high_noul_allows(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    mock_system_one.return_value = {
        "answers": {"escalate_reasoning": {"type": "noul", "noul": 0.95}}
    }
    assert jr.should_jev_allow_escalate("3 failed") is True


@patch("monitor.lib.jev_reasoning.tc.system_one")
def test_escalate_low_noul_blocks(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    monkeypatch.setenv("MONITOR_JEV_CONFIDENCE", "0.6")
    mock_system_one.return_value = {
        "answers": {"escalate_reasoning": {"type": "noul", "noul": 0.1}}
    }
    assert jr.should_jev_allow_escalate("error mentioned in docs") is False
