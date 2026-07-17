"""Tests for the per-turn tool-call loop detector (PLAN Phase 7).

Helpers live in ``monitor.lib.tool_failures``; ``handle_tool_call`` clears
state at ``_depth=0``.
"""

import monitor.config  # noqa: F401

import pytest

from monitor import config
from monitor.core import tooling
from monitor.lib import tool_failures


@pytest.fixture(autouse=True)
def _reset_recent_calls():
    tool_failures.reset_tool_hygiene_state()
    yield
    tool_failures.reset_tool_hygiene_state()


def test_signature_is_stable_across_arg_key_order():
    a = tool_failures.tool_call_signature("foo", {"x": 1, "y": 2})
    b = tool_failures.tool_call_signature("foo", {"y": 2, "x": 1})
    assert a == b


def test_signature_differs_for_different_args():
    a = tool_failures.tool_call_signature("foo", {"x": 1})
    b = tool_failures.tool_call_signature("foo", {"x": 2})
    assert a != b


def test_signature_differs_for_different_names():
    a = tool_failures.tool_call_signature("foo", {"x": 1})
    b = tool_failures.tool_call_signature("bar", {"x": 1})
    assert a != b


def test_signature_handles_non_serializable_args():
    sentinel = object()
    sig = tool_failures.tool_call_signature("foo", {"x": sentinel})
    assert sig.startswith("foo:")


def test_two_consecutive_same_calls_pass(monkeypatch):
    monkeypatch.setattr(config, "MAX_REPEATED_TOOL_CALLS", 3, raising=False)
    assert tool_failures.check_exact_repeat("read", {"p": "a"}) is None
    assert tool_failures.check_exact_repeat("read", {"p": "a"}) is None


def test_third_consecutive_same_call_trips(monkeypatch):
    monkeypatch.setattr(config, "MAX_REPEATED_TOOL_CALLS", 3, raising=False)
    tool_failures.check_exact_repeat("read", {"p": "a"})
    tool_failures.check_exact_repeat("read", {"p": "a"})
    assert tool_failures.check_exact_repeat("read", {"p": "a"}) is not None


def test_alternating_calls_never_trip(monkeypatch):
    monkeypatch.setattr(config, "MAX_REPEATED_TOOL_CALLS", 3, raising=False)
    for _ in range(5):
        assert tool_failures.check_exact_repeat("read", {"p": "a"}) is None
        assert tool_failures.check_exact_repeat("read", {"p": "b"}) is None


def test_different_args_resets_window(monkeypatch):
    monkeypatch.setattr(config, "MAX_REPEATED_TOOL_CALLS", 3, raising=False)
    assert tool_failures.check_exact_repeat("read", {"p": "a"}) is None
    assert tool_failures.check_exact_repeat("read", {"p": "a"}) is None
    assert tool_failures.check_exact_repeat("read", {"p": "b"}) is None
    assert tool_failures.check_exact_repeat("read", {"p": "a"}) is None
    assert tool_failures.check_exact_repeat("read", {"p": "a"}) is None


def test_threshold_of_two_trips_on_second(monkeypatch):
    monkeypatch.setattr(config, "MAX_REPEATED_TOOL_CALLS", 2, raising=False)
    assert tool_failures.check_exact_repeat("read", {"p": "a"}) is None
    assert tool_failures.check_exact_repeat("read", {"p": "a"}) is not None


def test_zero_threshold_disables_detector(monkeypatch):
    monkeypatch.setattr(config, "MAX_REPEATED_TOOL_CALLS", 0, raising=False)
    for _ in range(20):
        assert tool_failures.check_exact_repeat("read", {"p": "a"}) is None


def test_handle_tool_call_clears_ledger_at_depth_zero(monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_CALL_DEPTH", 8, raising=False)
    tool_failures._RECENT_TOOL_CALLS.extend(["stale:{}", "stale:{}"])

    try:
        tooling.handle_tool_call(response=None, _depth=0)
    except Exception:
        pass

    assert tool_failures._RECENT_TOOL_CALLS == []


def test_handle_tool_call_preserves_ledger_at_nonzero_depth(monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_CALL_DEPTH", 4, raising=False)
    tool_failures._RECENT_TOOL_CALLS.extend(["mid:{}", "mid:{}"])

    result = tooling.handle_tool_call(response=None, _depth=4)
    assert "Tool-call chain exceeded" in result
    assert tool_failures._RECENT_TOOL_CALLS == ["mid:{}", "mid:{}"]
