"""Tests for the per-turn tool-call loop detector in monitor.core.tooling.

Covers the pure helpers (_tool_call_signature, _check_repeated_call) and the
integration point: that the per-turn ledger clears at _depth=0 and that the
configurable threshold MAX_REPEATED_TOOL_CALLS is honored.
"""

# Pre-import config to head off the known import-cycle some monitor test
# modules trip when collected first.
import monitor.config  # noqa: F401

import pytest

from monitor import config
from monitor.core import tooling


@pytest.fixture(autouse=True)
def _reset_recent_calls():
    """Each test gets a clean ledger so cross-test state doesn't leak."""
    tooling._RECENT_TOOL_CALLS.clear()
    yield
    tooling._RECENT_TOOL_CALLS.clear()


def test_signature_is_stable_across_arg_key_order():
    """Same call with reordered kwargs must hash identically."""
    a = tooling._tool_call_signature("foo", {"x": 1, "y": 2})
    b = tooling._tool_call_signature("foo", {"y": 2, "x": 1})
    assert a == b


def test_signature_differs_for_different_args():
    a = tooling._tool_call_signature("foo", {"x": 1})
    b = tooling._tool_call_signature("foo", {"x": 2})
    assert a != b


def test_signature_differs_for_different_names():
    a = tooling._tool_call_signature("foo", {"x": 1})
    b = tooling._tool_call_signature("bar", {"x": 1})
    assert a != b


def test_signature_handles_non_serializable_args():
    """A non-JSON-serializable arg must not crash the detector."""
    sentinel = object()
    sig = tooling._tool_call_signature("foo", {"x": sentinel})
    assert sig.startswith("foo:")


def test_two_consecutive_same_calls_pass(monkeypatch):
    """At default MAX_REPEATED_TOOL_CALLS=3, two repeats are still fine."""
    monkeypatch.setattr(config, "MAX_REPEATED_TOOL_CALLS", 3, raising=False)
    assert tooling._check_repeated_call("read", {"p": "a"}) is False
    assert tooling._check_repeated_call("read", {"p": "a"}) is False


def test_third_consecutive_same_call_trips(monkeypatch):
    monkeypatch.setattr(config, "MAX_REPEATED_TOOL_CALLS", 3, raising=False)
    tooling._check_repeated_call("read", {"p": "a"})
    tooling._check_repeated_call("read", {"p": "a"})
    assert tooling._check_repeated_call("read", {"p": "a"}) is True


def test_alternating_calls_never_trip(monkeypatch):
    """A→B→A→B never triggers, even past the threshold count."""
    monkeypatch.setattr(config, "MAX_REPEATED_TOOL_CALLS", 3, raising=False)
    for _ in range(5):
        assert tooling._check_repeated_call("read", {"p": "a"}) is False
        assert tooling._check_repeated_call("read", {"p": "b"}) is False


def test_different_args_resets_window(monkeypatch):
    """A→A→B→A→A is fine because the last 3 entries are A,A,A? Wait, no:
    they are B,A,A — not all equal, so no trip. This guards against a naive
    'count occurrences anywhere in the ledger' implementation."""
    monkeypatch.setattr(config, "MAX_REPEATED_TOOL_CALLS", 3, raising=False)
    assert tooling._check_repeated_call("read", {"p": "a"}) is False
    assert tooling._check_repeated_call("read", {"p": "a"}) is False
    assert tooling._check_repeated_call("read", {"p": "b"}) is False
    assert tooling._check_repeated_call("read", {"p": "a"}) is False
    # Last 3: B, A, A — not uniform, no trip.
    assert tooling._check_repeated_call("read", {"p": "a"}) is False


def test_threshold_of_two_trips_on_second(monkeypatch):
    monkeypatch.setattr(config, "MAX_REPEATED_TOOL_CALLS", 2, raising=False)
    assert tooling._check_repeated_call("read", {"p": "a"}) is False
    assert tooling._check_repeated_call("read", {"p": "a"}) is True


def test_zero_threshold_disables_detector(monkeypatch):
    """0 (or negative) means the detector is off — repeats never trip."""
    monkeypatch.setattr(config, "MAX_REPEATED_TOOL_CALLS", 0, raising=False)
    for _ in range(20):
        assert tooling._check_repeated_call("read", {"p": "a"}) is False


def test_handle_tool_call_clears_ledger_at_depth_zero(monkeypatch):
    """A new user turn (entry at _depth=0) must wipe the ledger so the
    previous turn's signatures don't carry over."""
    monkeypatch.setattr(config, "MAX_TOOL_CALL_DEPTH", 8, raising=False)
    tooling._RECENT_TOOL_CALLS.extend(["stale:{}", "stale:{}"])

    # Run handle_tool_call at depth 0 with response=None. The call will fail
    # later (extract_tool_calls on None), but we only care that the ledger
    # was cleared at entry — which happens before the failing work.
    try:
        tooling.handle_tool_call(response=None, _depth=0)
    except Exception:
        pass

    assert tooling._RECENT_TOOL_CALLS == []


def test_handle_tool_call_preserves_ledger_at_nonzero_depth(monkeypatch):
    """Recursive entries (_depth>0) are mid-turn and must not wipe state."""
    monkeypatch.setattr(config, "MAX_TOOL_CALL_DEPTH", 4, raising=False)
    tooling._RECENT_TOOL_CALLS.extend(["mid:{}", "mid:{}"])

    # _depth >= MAX so the function bails out before doing real work, but
    # the depth==0 clear branch is skipped — ledger must survive.
    result = tooling.handle_tool_call(response=None, _depth=4)
    assert "Tool-call chain exceeded" in result
    assert tooling._RECENT_TOOL_CALLS == ["mid:{}", "mid:{}"]
