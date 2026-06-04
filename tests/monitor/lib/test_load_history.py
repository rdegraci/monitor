"""Tests for the :load_history built-in.

Counterpart to :dump_history — reads a saved JSON envelope back into
config.CONVERSATION_HISTORY and resets per-session counters. Tests
cover the validation paths (every rejection MUST leave state intact),
the happy round-trip via dump_history+load_history, and the staleness
warning that surfaces how old the saved session is.
"""

import json
import time

import pytest

# Pre-import config to head off the known import-cycle.
import monitor.config  # noqa: F401

from monitor import config
from monitor.lib import built_in_commands


SAVED_SESSION_ID = "test-saved-session"
SAVED_MODEL = "saved/model-xyz"


def _write_envelope(path, **overrides):
    """Build a valid :dump_history envelope on disk, with overrides for
    specific fields. Returns the parsed payload for assertions."""
    payload = {
        "schema_version": 1,
        "written_at": time.time(),
        "session_id": SAVED_SESSION_ID,
        "model": SAVED_MODEL,
        "conversation": [
            {"role": "system", "content": "sys prompt from saved session"},
            {"role": "user", "content": "what did we discuss?"},
            {"role": "assistant", "content": "we discussed X, Y, Z"},
        ],
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload))
    return payload


@pytest.fixture(autouse=True)
def _seed_active_session(monkeypatch):
    """Set up an existing session state so we can verify :load_history
    actually REPLACES it. Use a session_id that differs from the saved
    one to confirm we don't somehow restore the old one."""
    monkeypatch.setattr(config, "SESSION_ID", "test-active-session", raising=False)
    monkeypatch.setattr(config, "MODEL", "active/model-abc", raising=False)
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "system", "content": "active sys"},
        {"role": "user", "content": "active turn"},
    ], raising=False)
    monkeypatch.setattr(config, "TOTAL_TOKEN_COUNT", 1234, raising=False)
    monkeypatch.setattr(config, "SESSION_TOTAL_TOKENS", 5678, raising=False)
    monkeypatch.setattr(config, "SESSION_COST_USD", 0.42, raising=False)
    monkeypatch.setattr(config, "TURN_COSTS_USD", [0.10, 0.20, 0.12], raising=False)
    monkeypatch.setattr(config, "SESSION_TOOL_CALL_COUNT", 17, raising=False)
    monkeypatch.setattr(config, "SESSION_LOOP_DETECTOR_TRIPS", 3, raising=False)
    monkeypatch.setattr(config, "SESSION_COMPACTION_COUNT", 2, raising=False)
    monkeypatch.setattr(config, "RESPONSE_ID", "resp_existing", raising=False)
    monkeypatch.setattr(config, "CURRENT_TURN_REASONING_OVERRIDE", "high", raising=False)
    monkeypatch.setattr(config, "last_summary_time", 0, raising=False)
    yield


# ---------------------------------------------------------------------------
# Happy path: replaces history + resets counters
# ---------------------------------------------------------------------------


def test_load_history_replaces_conversation(tmp_path):
    src = tmp_path / "saved.json"
    payload = _write_envelope(src)

    built_in_commands.load_history_command(str(src))

    # The active session's "active sys" / "active turn" are gone; the
    # saved session's three messages took their place.
    assert config.CONVERSATION_HISTORY == payload["conversation"]
    assert len(config.CONVERSATION_HISTORY) == 3


def test_load_history_resets_per_session_counters(tmp_path):
    """Counters (cost, tokens, tool-call count, etc.) are session-scoped.
    A loaded session's metrics aren't ours to claim, so loading must
    zero them out — otherwise :cost_debug, U: indicator, and
    :dump_metrics would all show inflated numbers from a previous
    session that we just inherited but didn't actually pay for."""
    src = tmp_path / "saved.json"
    _write_envelope(src)

    built_in_commands.load_history_command(str(src))

    assert config.TOTAL_TOKEN_COUNT == 0
    assert config.SESSION_TOTAL_TOKENS == 0
    assert config.SESSION_COST_USD == 0.0
    assert config.TURN_COSTS_USD == []
    assert config.SESSION_TOOL_CALL_COUNT == 0
    assert config.SESSION_LOOP_DETECTOR_TRIPS == 0
    assert config.SESSION_COMPACTION_COUNT == 0
    assert config.RESPONSE_ID is None
    assert config.CURRENT_TURN_REASONING_OVERRIDE is None


def test_load_history_restarts_summary_clock(tmp_path):
    """last_summary_time anchors the time-based summarization trigger.
    Loading must reset it to "now" — otherwise the summarizer would
    think the last summary happened at session-write time (potentially
    days ago) and fire prematurely on the very next turn."""
    src = tmp_path / "saved.json"
    _write_envelope(src)
    before = time.time()
    built_in_commands.load_history_command(str(src))
    after = time.time()
    assert before <= config.last_summary_time <= after


def test_load_history_keeps_active_session_id_and_model(tmp_path):
    """The loaded envelope contains the SOURCE session's id and model.
    But we're a NEW session that just happens to be working from a
    saved transcript — keep the active session_id and current model.
    Otherwise :memory_save would tag entries under the old session_id,
    cross-wiring conversations in ways no one expects."""
    src = tmp_path / "saved.json"
    _write_envelope(src)
    built_in_commands.load_history_command(str(src))
    assert config.SESSION_ID == "test-active-session"
    assert config.MODEL == "active/model-abc"


# ---------------------------------------------------------------------------
# Validation: every rejection must leave state intact
# ---------------------------------------------------------------------------


def _snapshot_session_state():
    """Capture the current in-memory session state for "did anything
    change?" assertions in the failure-path tests."""
    return {
        "history": list(config.CONVERSATION_HISTORY),
        "total_token_count": config.TOTAL_TOKEN_COUNT,
        "session_total_tokens": config.SESSION_TOTAL_TOKENS,
        "session_cost_usd": config.SESSION_COST_USD,
        "turn_costs_usd": list(config.TURN_COSTS_USD),
        "session_tool_call_count": config.SESSION_TOOL_CALL_COUNT,
        "session_loop_detector_trips": config.SESSION_LOOP_DETECTOR_TRIPS,
        "session_compaction_count": config.SESSION_COMPACTION_COUNT,
        "response_id": config.RESPONSE_ID,
    }


def test_load_history_no_arg_prints_usage(capsys):
    before = _snapshot_session_state()
    built_in_commands.load_history_command("")
    after = _snapshot_session_state()
    assert before == after  # nothing mutated
    out = capsys.readouterr()
    assert "Usage" in (out.out + out.err)


def test_load_history_missing_file(tmp_path, capsys):
    before = _snapshot_session_state()
    built_in_commands.load_history_command(str(tmp_path / "no_such_file.json"))
    after = _snapshot_session_state()
    assert before == after
    out = capsys.readouterr()
    assert "not found" in (out.out + out.err).lower()


def test_load_history_invalid_json(tmp_path, capsys):
    bad = tmp_path / "garbage.json"
    bad.write_text("this is { not valid json")
    before = _snapshot_session_state()
    built_in_commands.load_history_command(str(bad))
    after = _snapshot_session_state()
    assert before == after
    out = capsys.readouterr()
    assert "parse" in (out.out + out.err).lower()


def test_load_history_envelope_must_be_dict(tmp_path, capsys):
    """A bare JSON array (e.g. someone hand-saved just the conversation
    list, not the envelope) must be rejected — we expect the dict
    wrapper that :dump_history writes."""
    bad = tmp_path / "array.json"
    bad.write_text('[{"role": "user", "content": "hi"}]')
    before = _snapshot_session_state()
    built_in_commands.load_history_command(str(bad))
    after = _snapshot_session_state()
    assert before == after
    out = capsys.readouterr()
    assert "object envelope" in (out.out + out.err)


def test_load_history_schema_version_mismatch(tmp_path, capsys):
    """schema_version != 1 must be rejected explicitly. A future v2
    envelope could have new fields we don't know how to interpret, and
    silently loading it would lose data. This is the future-proofing
    knob :dump_history baked in."""
    src = tmp_path / "future.json"
    _write_envelope(src, schema_version=2)
    before = _snapshot_session_state()
    built_in_commands.load_history_command(str(src))
    after = _snapshot_session_state()
    assert before == after
    out = capsys.readouterr()
    assert "schema_version" in (out.out + out.err)


def test_load_history_missing_conversation_key(tmp_path, capsys):
    src = tmp_path / "no_conv.json"
    src.write_text(json.dumps({"schema_version": 1, "written_at": time.time()}))
    before = _snapshot_session_state()
    built_in_commands.load_history_command(str(src))
    after = _snapshot_session_state()
    assert before == after
    out = capsys.readouterr()
    assert "conversation" in (out.out + out.err).lower()


def test_load_history_conversation_must_be_list(tmp_path, capsys):
    src = tmp_path / "wrong_shape.json"
    src.write_text(json.dumps({
        "schema_version": 1,
        "written_at": time.time(),
        "conversation": "not a list",
    }))
    before = _snapshot_session_state()
    built_in_commands.load_history_command(str(src))
    after = _snapshot_session_state()
    assert before == after
    out = capsys.readouterr()
    assert "list" in (out.out + out.err).lower()


# ---------------------------------------------------------------------------
# Staleness warning
# ---------------------------------------------------------------------------


def test_load_history_includes_staleness_warning(tmp_path, capsys):
    """The load message must surface elapsed time + the 'tool results
    may be stale' caution. This is the user-facing guardrail against
    trusting cat_file results from yesterday's filesystem state."""
    src = tmp_path / "saved.json"
    # written_at 2 hours ago.
    _write_envelope(src, written_at=time.time() - 7200)
    built_in_commands.load_history_command(str(src))
    out = capsys.readouterr().out
    assert "2h ago" in out
    assert "stale" in out.lower()


def test_load_history_elapsed_buckets(tmp_path, capsys):
    """Spot-check the _format_elapsed buckets through the public command."""
    src = tmp_path / "saved.json"

    # 30 seconds ago → "Ns ago"
    _write_envelope(src, written_at=time.time() - 30)
    built_in_commands.load_history_command(str(src))
    assert "30s ago" in capsys.readouterr().out

    # 5 minutes ago → "Nm ago"
    _write_envelope(src, written_at=time.time() - 300)
    built_in_commands.load_history_command(str(src))
    assert "5m ago" in capsys.readouterr().out

    # 3 days ago → "Nd ago"
    _write_envelope(src, written_at=time.time() - 86400 * 3)
    built_in_commands.load_history_command(str(src))
    assert "3d ago" in capsys.readouterr().out


def test_load_history_no_written_at_skips_warning(tmp_path, capsys):
    """If written_at is missing or invalid, just skip the staleness
    sentence rather than crashing or printing garbage."""
    src = tmp_path / "no_ts.json"
    src.write_text(json.dumps({
        "schema_version": 1,
        "conversation": [{"role": "user", "content": "x"}],
    }))
    built_in_commands.load_history_command(str(src))
    out = capsys.readouterr().out
    assert "Loaded 1 messages" in out
    # No "ago" string when there was no written_at to compute against.
    assert "ago" not in out


def test_load_history_source_session_id_in_message(tmp_path, capsys):
    """The load message surfaces the source session_id so the user can
    confirm which historical session got pulled in — distinct from the
    *current* session id, which is preserved."""
    src = tmp_path / "saved.json"
    _write_envelope(src)
    built_in_commands.load_history_command(str(src))
    out = capsys.readouterr().out
    assert SAVED_SESSION_ID in out
    assert SAVED_MODEL in out


# ---------------------------------------------------------------------------
# Round-trip with :dump_history
# ---------------------------------------------------------------------------


def test_dump_then_load_roundtrip(tmp_path):
    """The whole point of pairing dump + load: a dump'd file loads
    cleanly into another (or the same) session. Pin this end-to-end."""
    # Use the dump command on a known history, then load it back.
    saved_path = tmp_path / "roundtrip.json"
    test_history = [
        {"role": "system", "content": "round-trip sys"},
        {"role": "user", "content": "round-trip user"},
        {"role": "assistant", "content": "round-trip assistant"},
    ]
    config.CONVERSATION_HISTORY.clear()
    config.CONVERSATION_HISTORY.extend(test_history)

    built_in_commands.dump_history_command(str(saved_path))
    assert saved_path.exists()

    # Mutate the current history; reload should restore exactly.
    config.CONVERSATION_HISTORY.clear()
    config.CONVERSATION_HISTORY.append({"role": "user", "content": "mutation"})
    assert len(config.CONVERSATION_HISTORY) == 1

    built_in_commands.load_history_command(str(saved_path))

    assert config.CONVERSATION_HISTORY == test_history


# ---------------------------------------------------------------------------
# Tilde expansion + registration
# ---------------------------------------------------------------------------


def test_load_history_expands_user_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    src = tmp_path / "saved.json"
    _write_envelope(src)
    built_in_commands.load_history_command("~/saved.json")
    assert len(config.CONVERSATION_HISTORY) == 3


def test_load_history_is_registered_as_builtin():
    from monitor.core import built_ins
    from monitor.lib import built_ins_utils

    built_ins.configure_built_ins()

    names = [cmd.get("command") for cmd in built_ins_utils.built_in_functions]
    assert ":load_history" in names
