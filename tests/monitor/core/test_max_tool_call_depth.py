"""Tests for MAX_TOOL_CALL_DEPTH guardrails in handle_tool_call.

Covers:
- The hard abort path returns the error message and logs at ERROR level.
- A single half-way warning fires when depth crosses MAX // 2.
- The active limit is read from config at call time (tunable at runtime).
"""

import logging

from monitor import config
from monitor.core.tooling import handle_tool_call


def test_hard_abort_at_max_depth(caplog, monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_CALL_DEPTH", 8, raising=False)
    caplog.set_level(logging.ERROR, logger="monitor.core.tooling")

    result = handle_tool_call(response=None, _depth=8)

    assert "Tool-call chain exceeded the maximum depth of 8" in result
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("reached MAX_TOOL_CALL_DEPTH 8" in r.getMessage() for r in error_records)


def test_hard_abort_at_higher_default(caplog, monkeypatch):
    """The default is 128; verify the error message reports the active value
    not a hardcoded constant."""
    monkeypatch.setattr(config, "MAX_TOOL_CALL_DEPTH", 128, raising=False)
    caplog.set_level(logging.ERROR, logger="monitor.core.tooling")

    result = handle_tool_call(response=None, _depth=128)
    assert "maximum depth of 128" in result


def test_half_way_warning_fires_once(caplog, monkeypatch):
    """The warning must fire exactly when _depth == MAX // 2, not on every
    round past the threshold — otherwise the log gets spammed."""
    monkeypatch.setattr(config, "MAX_TOOL_CALL_DEPTH", 10, raising=False)
    caplog.set_level(logging.WARNING, logger="monitor.core.tooling")

    # At depth 5 (== 10 // 2), the warning should fire. We can't easily run
    # the full handle_tool_call recursion in a unit test, so we exercise the
    # threshold branch by inspecting the warning emitted before the function
    # tries to do real work (which will fail downstream — that's fine, we
    # only care that the warning is logged at this depth).
    try:
        handle_tool_call(response=None, _depth=5)
    except Exception:
        pass

    warning_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "half of MAX_TOOL_CALL_DEPTH" in r.getMessage()
    ]
    assert len(warning_records) == 1
    assert "depth 5 of 10" in warning_records[0].getMessage()


def test_no_warning_before_half_way(caplog, monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_CALL_DEPTH", 10, raising=False)
    caplog.set_level(logging.WARNING, logger="monitor.core.tooling")

    try:
        handle_tool_call(response=None, _depth=4)
    except Exception:
        pass

    warning_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "half of MAX_TOOL_CALL_DEPTH" in r.getMessage()
    ]
    assert len(warning_records) == 0


def test_no_warning_after_half_way(caplog, monkeypatch):
    """At depth > MAX // 2 the threshold warning must not re-fire — the
    equality check prevents spam."""
    monkeypatch.setattr(config, "MAX_TOOL_CALL_DEPTH", 10, raising=False)
    caplog.set_level(logging.WARNING, logger="monitor.core.tooling")

    try:
        handle_tool_call(response=None, _depth=6)
    except Exception:
        pass

    warning_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "half of MAX_TOOL_CALL_DEPTH" in r.getMessage()
    ]
    assert len(warning_records) == 0


def test_default_value_is_128():
    """Sanity check that nothing has accidentally regressed the default."""
    assert config.MAX_TOOL_CALL_DEPTH == 128
