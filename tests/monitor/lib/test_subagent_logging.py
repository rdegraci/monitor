import json
from pathlib import Path
import os
from monitor._stubs import appdirs

import pytest

from monitor.lib import subagent_logging


def test_append_interaction_writes_jsonl(tmp_path, monkeypatch):
    # Redirect user cache dir to tmp
    base_cache = tmp_path / "cache"
    monkeypatch.setattr(appdirs, "user_cache_dir", lambda name: str(base_cache))
    # Ensure no MONITOR_STATUS_SOCKET so fallback path used with explicit file
    target = tmp_path / "subagents" / "testsession.log"
    target.parent.mkdir(parents=True, exist_ok=True)

    # Call append_interaction with explicit path
    subagent_logging.append_interaction("Why is the sky blue?", "Because of Rayleigh scattering.", explicit_path=str(target))

    # Verify file created and contains valid JSONL line
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    lines = [l for l in content.splitlines() if l.strip()]
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["prompt_text"].startswith("Why is the sky")
    assert "Rayleigh" in obj["reply_text"]


def test_append_interaction_resolves_meta(monkeypatch, tmp_path):
    # Redirect user data dir to tmp
    base_data = tmp_path / "data"
    monkeypatch.setattr(appdirs, "user_data_dir", lambda name: str(base_data))
    subagents_dir = base_data / "subagents"
    subagents_dir.mkdir(parents=True, exist_ok=True)

    # Create a metadata file matching a socket path
    socket_path = str(tmp_path / "sock" / "agent.sock")
    log_file = tmp_path / "logs" / "meta_session.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "session_name": "meta_session",
        "created_at": "2026-03-23T00:00:00Z",
        "prompt": "hello",
        "log_path": str(log_file),
        "socket_path": socket_path,
    }
    meta_path = subagents_dir / "meta_session.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    # Set MONITOR_STATUS_SOCKET so append_interaction will find the metadata
    monkeypatch.setenv("MONITOR_STATUS_SOCKET", socket_path)

    subagent_logging.append_interaction("Q","A")

    assert log_file.exists()
    lines = [l for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines, "Expected at least one JSONL line"
    obj = json.loads(lines[-1])
    assert obj["prompt_text"] == "Q"
    assert obj["reply_text"] == "A"
