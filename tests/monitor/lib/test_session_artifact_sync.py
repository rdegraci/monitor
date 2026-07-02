import json
from types import SimpleNamespace

from monitor.lib import session_artifact_sync
from monitor.lib import session_artifacts


def test_build_feature_list_payload_uses_real_task_state() -> None:
    """Verify feature list payload is built from deterministic task state."""
    snapshot = session_artifact_sync.SessionArtifactSnapshot(
        todos=[{"id": "a1", "item": "Write tests", "status": "pending", "priority": 1, "notes": ""}],
        task_context={"acceptance_criteria": ["tests pass"]},
        last_checkpoint={"summary": "tests added", "next_step": "run pytest", "blockers": ""},
        scope_changes=[{"summary": "expand docs", "material": False}],
        acceptance_criteria=["tests pass"],
        changed_files=["src/monitor/core/conversation.py"],
    )

    payload = session_artifact_sync.build_feature_list_payload(snapshot)

    assert payload["todos"][0]["item"] == "Write tests"
    assert payload["acceptance_criteria"] == ["tests pass"]
    assert payload["checkpoint"]["next_step"] == "run pytest"
    assert payload["scope_changes"][0]["summary"] == "expand docs"


def test_build_progress_note_prefers_checkpoint_state() -> None:
    """Verify progress note is derived from checkpoint and scope-change state."""
    snapshot = session_artifact_sync.SessionArtifactSnapshot(
        todos=[],
        task_context={},
        last_checkpoint={
            "summary": "parser updated",
            "next_step": "run targeted tests",
            "blockers": "waiting on fixture",
            "updated_at": "2026-07-01T14:00:00Z",
        },
        scope_changes=[{"summary": "support config override", "material": True}],
        acceptance_criteria=[],
        changed_files=["src/monitor/lib/session_artifact_sync.py"],
    )

    note = session_artifact_sync.build_progress_note(snapshot)

    assert "Current summary: parser updated" in note
    assert "Next step: run targeted tests" in note
    assert "Updated at: 2026-07-01T14:00:00Z" in note
    assert "Blockers: waiting on fixture" in note
    assert "support config override" in note


def test_build_contract_note_only_records_material_scope_changes() -> None:
    """Verify contract note includes only material scope changes."""
    snapshot = session_artifact_sync.SessionArtifactSnapshot(
        todos=[],
        task_context={},
        last_checkpoint=None,
        scope_changes=[
            {"summary": "minor wording cleanup", "material": False},
            {"summary": "add crash recovery policy", "material": True},
        ],
        acceptance_criteria=[],
        changed_files=[],
    )

    contract = session_artifact_sync.build_contract_note(snapshot)

    assert "add crash recovery policy" in contract
    assert "minor wording cleanup" not in contract


def test_sync_session_artifacts_writes_all_files_deterministically(tmp_path, monkeypatch) -> None:
    """Verify sync writes feature list, progress, contract, and log from task state."""
    monkeypatch.setattr(session_artifacts.appdirs, "user_config_dir", lambda _name: str(tmp_path))
    monkeypatch.setattr(session_artifact_sync.config, "SESSION_ID", "session-123", raising=False)

    paths = session_artifacts.ensure_session_folder("20260101_12_34", "session-123")
    snapshot = session_artifact_sync.SessionArtifactSnapshot(
        todos=[
            {"id": "a1", "item": "Write tests", "status": "done", "priority": 2, "notes": ""},
            {"id": "a2", "item": "Verify docs", "status": "pending", "priority": 1, "notes": ""},
        ],
        task_context={"acceptance_criteria": ["tests pass"]},
        last_checkpoint={
            "summary": "tests added",
            "next_step": "verify docs",
            "blockers": "",
            "updated_at": "2026-07-01T14:10:00Z",
        },
        scope_changes=[{"summary": "expand docs", "material": True}],
        acceptance_criteria=["tests pass"],
        changed_files=["src/monitor/lib/session_artifact_sync.py", "docs/cache/DEV-SESSION-POLICY.md"],
    )

    monkeypatch.setattr(
        session_artifact_sync,
        "collect_session_artifact_snapshot",
        lambda: snapshot,
    )

    session_artifact_sync.sync_session_artifacts(paths)

    feature_payload = json.loads(paths.feature_list.read_text(encoding="utf-8"))
    progress_text = paths.progress.read_text(encoding="utf-8")
    contract_text = paths.contract.read_text(encoding="utf-8")
    log_text = paths.log.read_text(encoding="utf-8")

    assert feature_payload["session_id"] == "session-123"
    assert len(feature_payload["todos"]) == 2
    assert "verify docs" in progress_text
    assert "expand docs" in contract_text
    assert "turn | verify docs" in log_text
    assert "Completed action: 1 done / 2 tracked todos." in log_text
    assert "Todos: 1 done, 1 pending." in log_text
    assert "Scope change: expand docs" in log_text
    assert "Changed files: src/monitor/lib/session_artifact_sync.py, docs/cache/DEV-SESSION-POLICY.md" in log_text


def test_sync_session_artifacts_appends_log_without_overwriting(tmp_path, monkeypatch) -> None:
    """Verify repeated syncs append log entries instead of replacing prior history."""
    monkeypatch.setattr(session_artifacts.appdirs, "user_config_dir", lambda _name: str(tmp_path))
    monkeypatch.setattr(session_artifact_sync.config, "SESSION_ID", "session-123", raising=False)

    paths = session_artifacts.ensure_session_folder("20260101_12_34", "session-123")
    session_artifacts.seed_session_artifacts(paths, "session-123")

    first_snapshot = session_artifact_sync.SessionArtifactSnapshot(
        todos=[{"id": "a1", "item": "Draft policy", "status": "pending", "priority": 1, "notes": ""}],
        task_context={},
        last_checkpoint={"summary": "policy drafted", "next_step": "review policy", "blockers": ""},
        scope_changes=[],
        acceptance_criteria=[],
        changed_files=["docs/cache/DEV-SESSION-POLICY.md"],
    )
    second_snapshot = session_artifact_sync.SessionArtifactSnapshot(
        todos=[{"id": "a1", "item": "Draft policy", "status": "done", "priority": 1, "notes": ""}],
        task_context={},
        last_checkpoint={"summary": "policy approved", "next_step": "implement sync", "blockers": ""},
        scope_changes=[],
        acceptance_criteria=[],
        changed_files=["src/monitor/lib/session_artifact_sync.py"],
    )

    snapshots = [first_snapshot, second_snapshot]
    monkeypatch.setattr(
        session_artifact_sync,
        "collect_session_artifact_snapshot",
        lambda: snapshots.pop(0),
    )

    session_artifact_sync.sync_session_artifacts(paths)
    session_artifact_sync.sync_session_artifacts(paths)

    log_text = paths.log.read_text(encoding="utf-8")

    assert "turn | review policy" in log_text
    assert "turn | implement sync" in log_text
    assert log_text.count("## [") >= 3
