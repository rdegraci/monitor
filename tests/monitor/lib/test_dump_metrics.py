"""Tests for the :dump_metrics built-in.

dump_metrics_command writes a flat JSON snapshot of the session's
cost/token/behavioral counters to a path, for use by eval harnesses that
run monitor via --script. The fields are stable; tests pin both their
presence and their types so a downstream Aider-bench adapter (or similar)
can rely on the schema.
"""

import json
import os

import pytest

# Pre-import config to head off a known import-cycle when this file is
# collected before monitor.config has finished initializing.
import monitor.config  # noqa: F401

from monitor import config
from monitor.lib import built_in_commands


@pytest.fixture(autouse=True)
def _seed_counters(monkeypatch, tmp_path):
    """Seed the counters with known values per test, then restore."""
    monkeypatch.setattr(config, "SESSION_ID", "test-session-abc", raising=False)
    monkeypatch.setattr(config, "MODEL", "test/model-x", raising=False)
    monkeypatch.setattr(config, "SESSION_COST_USD", 1.2345, raising=False)
    monkeypatch.setattr(config, "SESSION_TOTAL_TOKENS", 9001, raising=False)
    monkeypatch.setattr(config, "TOTAL_TOKEN_COUNT", 4096, raising=False)
    monkeypatch.setattr(config, "LAST_REQUEST_TOKEN_COUNT", 512, raising=False)
    monkeypatch.setattr(config, "TURN_COSTS_USD", [0.10, 0.20, 0.30], raising=False)
    monkeypatch.setattr(config, "SESSION_TOOL_CALL_COUNT", 17, raising=False)
    monkeypatch.setattr(config, "SESSION_LOOP_DETECTOR_TRIPS", 2, raising=False)
    monkeypatch.setattr(config, "SESSION_COMPACTION_COUNT", 1, raising=False)
    monkeypatch.setattr(
        config,
        "CONVERSATION_HISTORY",
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "again"},
        ],
        raising=False,
    )
    yield


def test_dump_metrics_writes_expected_fields(tmp_path):
    out = tmp_path / "metrics.json"
    built_in_commands.dump_metrics_command(str(out))

    assert out.exists()
    payload = json.loads(out.read_text())

    assert payload["schema_version"] == 1
    assert payload["session_id"] == "test-session-abc"
    assert payload["model"] == "test/model-x"
    assert payload["session_cost_usd"] == pytest.approx(1.2345)
    assert payload["session_total_tokens"] == 9001
    assert payload["total_token_count"] == 4096
    assert payload["last_request_token_count"] == 512
    assert payload["turn_costs_usd"] == [0.10, 0.20, 0.30]
    assert payload["session_tool_call_count"] == 17
    assert payload["session_loop_detector_trips"] == 2
    assert payload["session_compaction_count"] == 1
    assert payload["conversation_length"] == 4
    assert payload["user_message_count"] == 2
    assert isinstance(payload["written_at"], (int, float))


def test_dump_metrics_expands_user_home(monkeypatch, tmp_path):
    """~ in the path must be expanded; the eval harness can't rely on
    the cwd of the launched monitor process."""
    monkeypatch.setenv("HOME", str(tmp_path))
    target = "~/metrics.json"
    built_in_commands.dump_metrics_command(target)
    assert (tmp_path / "metrics.json").exists()


def test_dump_metrics_overwrites_existing_file(tmp_path):
    """Overwrite is the right default — eval runs are idempotent on the
    output path within a per-task tempdir."""
    out = tmp_path / "metrics.json"
    out.write_text("garbage that should be replaced")
    built_in_commands.dump_metrics_command(str(out))
    payload = json.loads(out.read_text())
    assert payload["session_id"] == "test-session-abc"


def test_dump_metrics_rejects_missing_parent(tmp_path, capsys):
    """When the parent dir doesn't exist, fail loudly rather than auto-
    creating — keeps the harness in charge of where files live."""
    missing = tmp_path / "no_such_dir" / "metrics.json"
    built_in_commands.dump_metrics_command(str(missing))
    assert not missing.exists()
    captured = capsys.readouterr()
    assert "Parent directory does not exist" in (captured.out + captured.err)


def test_dump_metrics_no_path_prints_usage(capsys):
    built_in_commands.dump_metrics_command("")
    captured = capsys.readouterr()
    assert "Usage" in (captured.out + captured.err)
    built_in_commands.dump_metrics_command(None)
    captured = capsys.readouterr()
    assert "Usage" in (captured.out + captured.err)


def test_dump_metrics_handles_unset_globals(monkeypatch, tmp_path):
    """A freshly imported config may be missing some attributes; the dump
    must still produce a usable JSON file with sane defaults rather than
    crash. This guards against AttributeError if config evolves."""
    for attr in (
        "SESSION_COST_USD",
        "SESSION_TOTAL_TOKENS",
        "TOTAL_TOKEN_COUNT",
        "LAST_REQUEST_TOKEN_COUNT",
        "TURN_COSTS_USD",
        "SESSION_TOOL_CALL_COUNT",
        "SESSION_LOOP_DETECTOR_TRIPS",
        "SESSION_COMPACTION_COUNT",
        "CONVERSATION_HISTORY",
    ):
        monkeypatch.delattr(config, attr, raising=False)

    out = tmp_path / "metrics.json"
    built_in_commands.dump_metrics_command(str(out))
    payload = json.loads(out.read_text())

    assert payload["session_cost_usd"] == 0.0
    assert payload["session_total_tokens"] == 0
    assert payload["turn_costs_usd"] == []
    assert payload["session_tool_call_count"] == 0
    assert payload["session_loop_detector_trips"] == 0
    assert payload["conversation_length"] == 0
    assert payload["user_message_count"] == 0


def test_dump_metrics_is_registered_as_builtin():
    """The eval harness invokes :dump_metrics by name through the script
    runner, which dispatches on the built-ins registry — so the
    registration itself is load-bearing."""
    from monitor.core import built_ins
    from monitor.lib import built_ins_utils

    # Registration happens inside configure_built_ins(), which app.main()
    # calls during startup. Drive it explicitly so the test doesn't depend
    # on collection order.
    built_ins.configure_built_ins()

    found = next(
        (
            cmd
            for cmd in built_ins_utils.built_in_functions
            if cmd.get("command") == ":dump_metrics"
        ),
        None,
    )
    assert found is not None, "expected :dump_metrics to be registered as a built-in"
    assert callable(found.get("function"))
