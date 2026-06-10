"""Tests for the :cost_debug built-in command.

The command prints a dump of cost-tracking state and flags two invariants:
1. len(TURN_COSTS_USD) == count of user-role messages in CONVERSATION_HISTORY
2. sum(TURN_COSTS_USD) == SESSION_COST_USD

These tests pin both the OK case (clean state shows OK markers) and the
two failure modes (each invariant violation surfaces a clear MISMATCH or
DRIFT message).
"""

import re

import pytest

import monitor.config  # noqa: F401 — break import cycle
from monitor import config
from monitor.lib.built_in_commands import cost_debug_command


def _set_state(monkeypatch, *, cost, tokens, buckets, history):
    monkeypatch.setattr(config, "SESSION_COST_USD", cost, raising=False)
    monkeypatch.setattr(config, "SESSION_TOTAL_TOKENS", tokens, raising=False)
    monkeypatch.setattr(config, "TURN_COSTS_USD", buckets, raising=False)
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", history, raising=False)


def _user(c="hi"):
    return {"role": "user", "content": c}


def _assistant(c="reply"):
    return {"role": "assistant", "content": c}


def test_dumps_cumulative_and_buckets(capsys, monkeypatch):
    _set_state(
        monkeypatch,
        cost=0.50,
        tokens=12345,
        buckets=[0.20, 0.30],
        history=[_user(), _assistant(), _user()],
    )
    cost_debug_command()
    out = capsys.readouterr().out

    assert "SESSION_COST_USD:    $0.500000" in out
    assert "SESSION_TOTAL_TOKENS: 12345" in out
    assert "Per-turn buckets:    2" in out
    assert "[  0]: $0.200000" in out
    assert "[  1]: $0.300000" in out


def test_clean_state_shows_ok_markers(capsys, monkeypatch):
    _set_state(
        monkeypatch,
        cost=0.50,
        tokens=1000,
        buckets=[0.20, 0.30],
        history=[_user(), _assistant(), _user()],
    )
    cost_debug_command()
    out = capsys.readouterr().out

    # Both invariants OK.
    assert "OK  bucket_count == user_message_count" in out
    assert "OK  sum(buckets) == cumulative" in out


def test_flags_bucket_count_mismatch(capsys, monkeypatch):
    """3 user messages but only 2 buckets — bucket-open dropped one
    somewhere. The command must surface this loudly."""
    _set_state(
        monkeypatch,
        cost=0.50,
        tokens=1000,
        buckets=[0.20, 0.30],   # 2 buckets
        history=[_user(), _assistant(), _user(), _assistant(), _user()],  # 3 users
    )
    cost_debug_command()
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert "MISMATCH" in combined
    assert "bucket_count=2" in combined
    assert "user_message_count=3" in combined


def test_flags_cumulative_drift(capsys, monkeypatch):
    """Cumulative is $1.00 but bucket sum is $0.50 — some cost grew the
    cumulative without growing a bucket. The DRIFT branch must fire and
    point at the likely culprit."""
    _set_state(
        monkeypatch,
        cost=1.00,
        tokens=1000,
        buckets=[0.20, 0.30],
        history=[_user(), _user()],
    )
    cost_debug_command()
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert "DRIFT" in combined
    assert "$0.500000" in combined  # bucket sum
    assert "$1.000000" in combined  # cumulative
    # The diagnostic points the user at the right code location.
    assert "token_management.py" in combined


def test_marks_zero_buckets(capsys, monkeypatch):
    """Zero-cost buckets are flagged inline so the user can spot them
    when scanning the dump. That's the whole point of running the command."""
    _set_state(
        monkeypatch,
        cost=0.40,
        tokens=1000,
        buckets=[0.20, 0.20, 0.0],
        history=[_user(), _user(), _user()],
    )
    cost_debug_command()
    out = capsys.readouterr().out

    # The zero entry has the ZERO marker; the non-zero ones don't.
    assert "[  2]: $0.000000  <-- ZERO" in out
    # Non-zero rows should not be marked.
    assert "$0.200000  <-- ZERO" not in out


def test_empty_state_reports_empty_buckets(capsys, monkeypatch):
    _set_state(
        monkeypatch,
        cost=0.0,
        tokens=0,
        buckets=[],
        history=[],
    )
    cost_debug_command()
    out = capsys.readouterr().out

    assert "Bucket list is empty." in out
    # Trivially satisfies both invariants (0 == 0, sum 0 == cumulative 0).
    assert "OK  bucket_count == user_message_count (0)" in out


def test_registered_in_built_ins():
    """Sanity check that :cost_debug is registered so a fresh session can
    invoke it. Run after configure_built_ins ships at startup so the
    command is available in the live REPL."""
    from monitor.core.built_ins import configure_built_ins
    # configure_built_ins is idempotent; running it from a test is safe.
    configure_built_ins()
    # Built-ins like :tasks, :ttl, :cost_debug live in the built-in
    # registry, not INTERNAL_COMMANDS — use the appropriate classifier.
    from monitor.lib.built_ins_utils import is_built_in_function
    assert is_built_in_function(":cost_debug") is not None
    assert is_built_in_function("/cost_debug") is not None
    assert is_built_in_function("cost_debug") is None
