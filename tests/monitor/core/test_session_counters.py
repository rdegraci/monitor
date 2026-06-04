"""Tests for the session-wide tool-call counters in monitor.core.tooling.

handle_tool_call increments two counters on every tool call it sees this
session: SESSION_TOOL_CALL_COUNT (every dispatch) and
SESSION_LOOP_DETECTOR_TRIPS (every call rejected by the loop detector).
These counters back the eval harness's :dump_metrics output.

Tests drive the per-tool-call loop directly via a stubbed tool table,
avoiding the get_llm_completion + history machinery — we only care that
the counters move at the right times.
"""

import monitor.config  # noqa: F401 - pre-import for the known import cycle

import pytest

from monitor import config
from monitor.core import tooling


class _StubResponse:
    """Minimal response shape that extract_tool_calls accepts.

    extract_tool_calls (in monitor.core.conversation) reads the OpenAI-
    style ``response.choices[0].message.tool_calls``. A plain dict-shape
    works through the same path; using an object with attributes mirrors
    what providers actually return.
    """

    def __init__(self, tool_calls):
        msg = type("Msg", (), {})()
        msg.tool_calls = tool_calls
        msg.content = None
        choice = type("Choice", (), {})()
        choice.message = msg
        choice.finish_reason = "tool_calls"
        self.choices = [choice]


def _tc(call_id, name, args_str):
    """Build a tool_call dict in the dispatcher's expected shape."""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": args_str},
    }


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Zero the counters and the loop-detector ledger before each test."""
    monkeypatch.setattr(config, "SESSION_TOOL_CALL_COUNT", 0, raising=False)
    monkeypatch.setattr(config, "SESSION_LOOP_DETECTOR_TRIPS", 0, raising=False)
    monkeypatch.setattr(config, "MAX_TOOL_CALL_DEPTH", 128, raising=False)
    monkeypatch.setattr(config, "MAX_REPEATED_TOOL_CALLS", 3, raising=False)
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [], raising=False)
    tooling._RECENT_TOOL_CALLS.clear()
    yield
    tooling._RECENT_TOOL_CALLS.clear()


def _patch_tool_loop(monkeypatch, recorded):
    """Wire enough stubs that the per-tool-call loop in handle_tool_call
    runs to the end and then short-circuits before recursing.

    - AVAILABLE_TOOLS["noop"] just appends args to ``recorded`` so we can
      verify the actual call happened (or didn't, in the loop-detector case).
    - get_llm_completion returns (None, "stop") so handle_tool_call exits
      without recursing further.
    - append_to_history_with_count is a no-op.
    """
    from monitor.lib import tool_definitions
    monkeypatch.setitem(
        tool_definitions.AVAILABLE_TOOLS,
        "noop",
        lambda **kwargs: recorded.append(kwargs) or "ok",
    )

    from monitor.core import conversation

    def _stub_extract(response):
        return response.choices[0].message.tool_calls

    def _stub_completion():
        return None, "stop-here"

    def _stub_append(*_a, **_kw):
        return None

    monkeypatch.setattr(conversation, "extract_tool_calls", _stub_extract, raising=False)
    monkeypatch.setattr(conversation, "get_llm_completion", _stub_completion, raising=False)
    monkeypatch.setattr(
        conversation, "append_to_history_with_count", _stub_append, raising=False
    )


def test_tool_call_count_increments_per_call(monkeypatch):
    recorded = []
    _patch_tool_loop(monkeypatch, recorded)

    resp = _StubResponse(
        [
            _tc("a", "noop", '{"x": 1}'),
            _tc("b", "noop", '{"x": 2}'),
            _tc("c", "noop", '{"x": 3}'),
        ]
    )
    tooling.handle_tool_call(resp, _depth=0)

    assert config.SESSION_TOOL_CALL_COUNT == 3
    assert config.SESSION_LOOP_DETECTOR_TRIPS == 0
    # All three calls actually executed (counter bumps did not gate them).
    assert recorded == [{"x": 1}, {"x": 2}, {"x": 3}]


def test_loop_detector_trip_increments_only_trip_counter(monkeypatch):
    """Three identical calls — the third is rejected by the loop detector.
    Tool-call count goes up by 3 (we count what was *seen*); trip count by 1.
    Only the first two actually execute."""
    recorded = []
    _patch_tool_loop(monkeypatch, recorded)

    same = '{"path": "foo.py"}'
    resp = _StubResponse(
        [
            _tc("a", "noop", same),
            _tc("b", "noop", same),
            _tc("c", "noop", same),
        ]
    )
    tooling.handle_tool_call(resp, _depth=0)

    assert config.SESSION_TOOL_CALL_COUNT == 3
    assert config.SESSION_LOOP_DETECTOR_TRIPS == 1
    # First two went through; the third was refused before execution.
    assert recorded == [{"path": "foo.py"}, {"path": "foo.py"}]


def test_counters_accumulate_across_turns(monkeypatch):
    """A new user turn enters at _depth=0 and clears the per-turn loop
    ledger — but the session-wide counters must keep going. This is the
    invariant the eval harness depends on."""
    recorded = []
    _patch_tool_loop(monkeypatch, recorded)

    # Turn 1: three identical calls, one trip.
    same = '{"path": "foo.py"}'
    tooling.handle_tool_call(
        _StubResponse([_tc("a", "noop", same)] * 3),
        _depth=0,
    )
    assert config.SESSION_TOOL_CALL_COUNT == 3
    assert config.SESSION_LOOP_DETECTOR_TRIPS == 1

    # Turn 2: two different calls, no trip — but counters carry over.
    tooling.handle_tool_call(
        _StubResponse(
            [_tc("a", "noop", '{"x": 1}'), _tc("b", "noop", '{"x": 2}')]
        ),
        _depth=0,
    )
    assert config.SESSION_TOOL_CALL_COUNT == 5
    assert config.SESSION_LOOP_DETECTOR_TRIPS == 1
