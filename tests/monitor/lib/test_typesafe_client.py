"""Tests for monitor.lib.typesafe_client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from monitor.lib import typesafe_client as tc


@pytest.fixture(autouse=True)
def _clear_jev_env(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("MONITOR_JEV", raising=False)
    monkeypatch.delenv("MONITOR_JEV_CONFIDENCE", raising=False)


def test_is_enabled_false_without_key():
    assert tc.is_enabled() is False


def test_is_enabled_true_with_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test-key")
    assert tc.is_enabled() is True


def test_is_enabled_false_when_kill_switch_off(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test-key")
    monkeypatch.setenv("MONITOR_JEV", "0")
    assert tc.is_enabled() is False
    monkeypatch.setenv("MONITOR_JEV", "false")
    assert tc.is_enabled() is False
    monkeypatch.setenv("MONITOR_JEV", "off")
    assert tc.is_enabled() is False


def test_confidence_floor_default():
    assert tc.confidence_floor() == tc.DEFAULT_CONFIDENCE_FLOOR


def test_confidence_floor_override(monkeypatch):
    monkeypatch.setenv("MONITOR_JEV_CONFIDENCE", "0.75")
    assert tc.confidence_floor() == 0.75


def test_confidence_floor_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("MONITOR_JEV_CONFIDENCE", "nope")
    assert tc.confidence_floor() == tc.DEFAULT_CONFIDENCE_FLOOR


def test_system_one_returns_none_when_disabled():
    assert tc.system_one("state", {"q": {"type": "noul", "instructions": "x"}}) is None


@patch("monitor.lib.typesafe_client.requests.post")
def test_system_one_success(mock_post, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test-key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "model": "jev-1.13.0",
        "answers": {
            "q": {"type": "choice", "choice": "surgical", "confidence": 0.9}
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    mock_post.return_value = mock_resp

    result = tc.system_one(
        "edit this file",
        {
            "q": {
                "type": "choice",
                "instructions": "route",
                "criteria": {"surgical": "a", "regen": "b", "read_more": "c"},
            }
        },
    )
    assert result is not None
    assert result["answers"]["q"]["choice"] == "surgical"
    mock_post.assert_called_once()
    kwargs = mock_post.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer ts-test-key"


@patch("monitor.lib.typesafe_client.requests.post")
def test_system_one_soft_fails_on_401(mock_post, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-bad")
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "unauthorized"
    mock_post.return_value = mock_resp
    assert tc.system_one("s", {"q": {"type": "noul", "instructions": "x"}}) is None


@patch("monitor.lib.typesafe_client.requests.post")
def test_system_one_soft_fails_on_malformed_json(mock_post, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test-key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = ValueError("not json")
    mock_post.return_value = mock_resp
    assert tc.system_one("s", {"q": {"type": "noul", "instructions": "x"}}) is None


@patch("monitor.lib.typesafe_client.time.sleep")
@patch("monitor.lib.typesafe_client.requests.post")
def test_system_one_retries_429_then_succeeds(mock_post, _sleep, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test-key")
    busy = MagicMock()
    busy.status_code = 429
    busy.text = "slow down"
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"answers": {}, "model": "jev-latest"}
    mock_post.side_effect = [busy, ok]
    result = tc.system_one("s", {"q": {"type": "noul", "instructions": "x"}})
    assert result is not None
    assert mock_post.call_count == 2


def test_choice_answer_extracts():
    response = {
        "answers": {
            "edit_route": {
                "type": "choice",
                "choice": "regen",
                "confidence": 0.8,
                "probabilities": {"regen": 0.8, "surgical": 0.2},
            }
        }
    }
    answer = tc.choice_answer(response, "edit_route")
    assert answer is not None
    assert answer["choice"] == "regen"


def test_choice_answer_none_on_bad_shape():
    assert tc.choice_answer(None, "x") is None
    assert tc.choice_answer({"answers": {}}, "x") is None
    assert tc.choice_answer(
        {"answers": {"x": {"type": "noul", "noul": 1.0}}}, "x"
    ) is None
