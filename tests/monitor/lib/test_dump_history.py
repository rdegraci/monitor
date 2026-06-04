"""Tests for the :dump_history built-in.

Companion to :dump_metrics — writes the full conversation history as a
JSON envelope. The eval harness uses this when LLM-driven failure
analysis needs to see the whole transcript, not just aggregate counters.

Schema is pinned: tests assert key names and types so a downstream
analyzer (or run-diff tool) can rely on the shape across monitor
revisions.
"""

import json

import pytest

# Pre-import config to head off the known import-cycle when this file is
# collected before monitor.config has finished initializing.
import monitor.config  # noqa: F401

from monitor import config
from monitor.lib import built_in_commands


@pytest.fixture(autouse=True)
def _seed_history(monkeypatch):
    monkeypatch.setattr(config, "SESSION_ID", "test-session-abc", raising=False)
    monkeypatch.setattr(config, "MODEL", "test/model-x", raising=False)
    monkeypatch.setattr(
        config,
        "CONVERSATION_HISTORY",
        [
            {"role": "system", "content": "you are a helpful assistant"},
            {"role": "user", "content": "fix the bug"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "cat_file", "arguments": '{"path": "foo.py"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "file contents..."},
            {"role": "assistant", "content": "Done!"},
        ],
        raising=False,
    )
    yield


def test_dump_history_writes_envelope_and_full_conversation(tmp_path):
    out = tmp_path / "history.json"
    built_in_commands.dump_history_command(str(out))

    assert out.exists()
    payload = json.loads(out.read_text())

    assert payload["schema_version"] == 1
    assert payload["session_id"] == "test-session-abc"
    assert payload["model"] == "test/model-x"
    assert isinstance(payload["written_at"], (int, float))
    assert isinstance(payload["conversation"], list)
    assert len(payload["conversation"]) == 5
    # Roles must round-trip exactly — analyzers filter on them.
    assert [m["role"] for m in payload["conversation"]] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    # Tool calls must serialize structurally, not flattened to a string.
    assistant_with_tools = payload["conversation"][2]
    assert assistant_with_tools["tool_calls"][0]["function"]["name"] == "cat_file"


def test_dump_history_deep_copies_so_later_mutation_does_not_leak(monkeypatch, tmp_path):
    """If we held a reference to the live history list and the test
    mutated it between dump and file write, the written file would still
    show the original snapshot. The dump captures the state at call
    time, period."""
    out = tmp_path / "history.json"
    built_in_commands.dump_history_command(str(out))

    # Mutate the live history after the dump.
    config.CONVERSATION_HISTORY.append({"role": "user", "content": "added later"})

    payload = json.loads(out.read_text())
    assert len(payload["conversation"]) == 5
    assert all(m["content"] != "added later" for m in payload["conversation"])


def test_dump_history_expands_user_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    built_in_commands.dump_history_command("~/history.json")
    assert (tmp_path / "history.json").exists()


def test_dump_history_overwrites_existing(tmp_path):
    out = tmp_path / "history.json"
    out.write_text("stale content")
    built_in_commands.dump_history_command(str(out))
    payload = json.loads(out.read_text())
    assert payload["session_id"] == "test-session-abc"


def test_dump_history_rejects_missing_parent(tmp_path, capsys):
    missing = tmp_path / "no_such_dir" / "history.json"
    built_in_commands.dump_history_command(str(missing))
    assert not missing.exists()
    out = capsys.readouterr()
    assert "Parent directory does not exist" in (out.out + out.err)


def test_dump_history_no_path_prints_usage(capsys):
    built_in_commands.dump_history_command("")
    out = capsys.readouterr()
    assert "Usage" in (out.out + out.err)
    built_in_commands.dump_history_command(None)
    out = capsys.readouterr()
    assert "Usage" in (out.out + out.err)


def test_dump_history_handles_unset_history(monkeypatch, tmp_path):
    """Right after startup, before any conversation, the history may be
    None or empty. The dump must produce a valid (if empty) envelope
    rather than crash."""
    monkeypatch.delattr(config, "CONVERSATION_HISTORY", raising=False)
    out = tmp_path / "history.json"
    built_in_commands.dump_history_command(str(out))
    payload = json.loads(out.read_text())
    assert payload["conversation"] == []


def test_dump_history_handles_non_serializable_payload(tmp_path):
    """Tool-call payloads can contain provider-SDK objects that aren't
    JSON-serializable. The dump must degrade them via default=str rather
    than failing and losing the entire transcript."""
    class WeirdObj:
        def __repr__(self):
            return "<WeirdObj>"

    config.CONVERSATION_HISTORY.append(
        {"role": "tool", "content": "ok", "metadata": WeirdObj()}
    )

    out = tmp_path / "history.json"
    built_in_commands.dump_history_command(str(out))
    payload = json.loads(out.read_text())
    last = payload["conversation"][-1]
    assert "<WeirdObj>" in str(last["metadata"])


def test_dump_history_is_registered_as_builtin():
    """The eval runner appends :dump_history to its generated script and
    dispatches via the built-ins table — the registration is what makes
    that work."""
    from monitor.core import built_ins
    from monitor.lib import built_ins_utils

    built_ins.configure_built_ins()

    found = next(
        (
            cmd
            for cmd in built_ins_utils.built_in_functions
            if cmd.get("command") == ":dump_history"
        ),
        None,
    )
    assert found is not None, "expected :dump_history to be registered"
    assert callable(found.get("function"))
