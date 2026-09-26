"""Tests for monitor.lib.jev_edit_route."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from monitor.lib import jev_edit_route as jer


@pytest.fixture(autouse=True)
def _clear_jev_env(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("MONITOR_JEV", raising=False)
    monkeypatch.delenv("MONITOR_JEV_CONFIDENCE", raising=False)


def test_decide_disabled_allows_regen():
    decision = jer.decide_edit_route("a.py", "fix typo")
    assert decision.acted is False
    assert decision.route == jer.ROUTE_REGEN
    assert decision.reason == "jev_disabled"


@patch("monitor.lib.jev_edit_route.tc.system_one")
def test_decide_high_conf_surgical_steers(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    mock_system_one.return_value = {
        "answers": {
            "edit_route": {
                "type": "choice",
                "choice": "surgical",
                "confidence": 0.95,
                "probabilities": {
                    "surgical": 0.9,
                    "regen": 0.05,
                    "read_more": 0.05,
                },
            }
        }
    }
    decision = jer.decide_edit_route("a.py", "rename foo to bar")
    assert decision.acted is True
    assert decision.route == jer.ROUTE_SURGICAL
    assert decision.guidance is not None
    assert "text_file_str_replace_in_file" in decision.guidance


@patch("monitor.lib.jev_edit_route.tc.system_one")
def test_decide_high_conf_read_more_steers(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    mock_system_one.return_value = {
        "answers": {
            "edit_route": {
                "type": "choice",
                "choice": "read_more",
                "confidence": 0.88,
            }
        }
    }
    decision = jer.decide_edit_route("a.py", "make it better")
    assert decision.acted is True
    assert decision.route == jer.ROUTE_READ_MORE
    assert "cat_file" in (decision.guidance or "")


@patch("monitor.lib.jev_edit_route.tc.system_one")
def test_decide_regen_does_not_steer(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    mock_system_one.return_value = {
        "answers": {
            "edit_route": {
                "type": "choice",
                "choice": "regen",
                "confidence": 0.99,
            }
        }
    }
    decision = jer.decide_edit_route("a.py", "rewrite idiomatic")
    assert decision.acted is False
    assert decision.route == jer.ROUTE_REGEN


@patch("monitor.lib.jev_edit_route.tc.system_one")
def test_decide_low_confidence_fallback(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    monkeypatch.setenv("MONITOR_JEV_CONFIDENCE", "0.8")
    mock_system_one.return_value = {
        "answers": {
            "edit_route": {
                "type": "choice",
                "choice": "surgical",
                "confidence": 0.5,
            }
        }
    }
    decision = jer.decide_edit_route("a.py", "fix typo")
    assert decision.acted is False
    assert decision.reason == "low_confidence"


@patch("monitor.lib.jev_edit_route.tc.system_one", return_value=None)
def test_decide_no_answer_fallback(_mock, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    decision = jer.decide_edit_route("a.py", "fix")
    assert decision.acted is False
    assert decision.reason == "no_answer"


@patch("monitor.lib.jev_edit_route.decide_edit_route")
def test_maybe_steer_returns_guidance(mock_decide):
    mock_decide.return_value = jer.EditRouteDecision(
        route=jer.ROUTE_SURGICAL,
        confidence=0.9,
        acted=True,
        reason="steered",
        guidance="STEER_ME",
    )
    msg = jer.maybe_steer_modify_source_code(
        {"source_file": "a.py", "modification_request": "x"}
    )
    assert msg == "STEER_ME"


@patch("monitor.lib.jev_edit_route.decide_edit_route")
def test_maybe_steer_none_when_not_acted(mock_decide):
    mock_decide.return_value = jer.EditRouteDecision(
        route=jer.ROUTE_REGEN,
        confidence=0.9,
        acted=False,
        reason="regen",
    )
    assert (
        jer.maybe_steer_modify_source_code(
            {"source_file": "a.py", "modification_request": "x"}
        )
        is None
    )
