from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from monitor import config
from monitor.lib import todo as todo_lib
from monitor.lib.session_artifacts import (
    SessionArtifactPaths,
    append_log_entry,
    write_contract,
    write_feature_list,
    write_progress_note,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SessionArtifactSnapshot:
    """Structured snapshot of session state for artifact writes."""

    todos: list[dict[str, Any]]
    task_context: dict[str, Any]
    last_checkpoint: dict[str, Any] | None
    scope_changes: list[dict[str, Any]]
    acceptance_criteria: list[str]
    changed_files: list[str]


def collect_session_artifact_snapshot() -> SessionArtifactSnapshot:
    """Collect the current session state used to drive artifact writes.

    Returns:
        A structured snapshot based on the todo store and task context.
    """
    todos_raw = json.loads(todo_lib.list_todos(emit_summary=False))
    context_raw = json.loads(todo_lib.get_task_context(emit_summary=False))
    checkpoint = context_raw.get("checkpoint") if isinstance(context_raw, dict) else None
    scope_changes = context_raw.get("scope_changes") if isinstance(context_raw, dict) else []
    acceptance_criteria = (
        context_raw.get("acceptance_criteria") if isinstance(context_raw, dict) else []
    )
    changed_files = []
    conversation_history = getattr(config, "CONVERSATION_HISTORY", []) or []
    for message in reversed(conversation_history):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        for line in content.splitlines():
            line = line.strip()
            if not line or "/" not in line:
                continue
            candidate = Path(line)
            if candidate.suffix and len(line) < 200:
                changed_files.append(line)
        if changed_files:
            break
    return SessionArtifactSnapshot(
        todos=todos_raw if isinstance(todos_raw, list) else [],
        task_context=context_raw if isinstance(context_raw, dict) else {},
        last_checkpoint=checkpoint if isinstance(checkpoint, dict) else None,
        scope_changes=scope_changes if isinstance(scope_changes, list) else [],
        acceptance_criteria=acceptance_criteria if isinstance(acceptance_criteria, list) else [],
        changed_files=changed_files[:5],
    )


def build_feature_list_payload(snapshot: SessionArtifactSnapshot) -> dict[str, Any]:
    """Build a deterministic feature-list payload from task state.

    Args:
        snapshot: Current session snapshot.

    Returns:
        JSON-serializable payload for feature_list.json.
    """
    return {
        "acceptance_criteria": snapshot.acceptance_criteria,
        "checkpoint": snapshot.last_checkpoint,
        "scope_changes": snapshot.scope_changes,
        "session_id": getattr(config, "SESSION_ID", None),
        "todos": snapshot.todos,
    }


def build_progress_note(snapshot: SessionArtifactSnapshot) -> str:
    """Build the current progress note from task state.

    Args:
        snapshot: Current session snapshot.

    Returns:
        Markdown progress note.
    """
    lines = ["# Session Progress", ""]
    checkpoint = snapshot.last_checkpoint or {}
    summary = str(checkpoint.get("summary", "")).strip()
    next_step = str(checkpoint.get("next_step", "")).strip()
    blockers = str(checkpoint.get("blockers", "")).strip()

    if summary:
        lines.append(f"- Current summary: {summary}")
    else:
        lines.append("- Current summary: No checkpoint recorded yet.")

    if next_step:
        lines.append(f"- Next step: {next_step}")
    else:
        lines.append("- Next step: Continue the current plan.")

    updated_at = str(checkpoint.get("updated_at", "")).strip()
    if updated_at:
        lines.append(f"- Updated at: {updated_at}")

    if blockers:
        lines.append(f"- Blockers: {blockers}")
    else:
        lines.append("- Blockers: None recorded.")

    lines.append("")
    lines.append("## Recent scope changes")
    if snapshot.scope_changes:
        for entry in snapshot.scope_changes[-3:]:
            if not isinstance(entry, dict):
                continue
            flag = "material" if entry.get("material") else "minor"
            lines.append(f"- [{flag}] {entry.get('summary', '')}")
    else:
        lines.append("- None recorded.")

    return "\n".join(lines).rstrip() + "\n"


def build_contract_note(snapshot: SessionArtifactSnapshot) -> str:
    """Build the current contract note from material scope changes.

    Args:
        snapshot: Current session snapshot.

    Returns:
        Markdown contract note.
    """
    lines = ["# Session Contract", ""]
    lines.append("- Maintain the contract as requirements evolve.")
    lines.append("- Keep the progress note updated with meaningful milestones.")
    lines.append("- Track planned and completed work in the feature list.")
    lines.append("- Append important events and decisions to the log.")
    material_changes = [
        entry
        for entry in snapshot.scope_changes
        if isinstance(entry, dict) and entry.get("material")
    ]
    if material_changes:
        lines.append("")
        lines.append("## Material scope changes")
        for entry in material_changes[-5:]:
            lines.append(f"- {entry.get('summary', '')}")
    return "\n".join(lines).rstrip() + "\n"


def build_log_entry(snapshot: SessionArtifactSnapshot) -> tuple[str, str, str]:
    """Build a compact append-only log entry from current state.

    Args:
        snapshot: Current session snapshot.

    Returns:
        A tuple of ``(op, title, body)`` for ``append_log_entry``.
    """
    checkpoint = snapshot.last_checkpoint or {}
    title = str(checkpoint.get("next_step") or checkpoint.get("summary") or "Session turn")
    body_lines = []
    summary = str(checkpoint.get("summary", "")).strip()
    next_step = str(checkpoint.get("next_step", "")).strip()
    if summary:
        body_lines.append(f"Milestone: {summary}")
    if next_step:
        body_lines.append(f"Next step: {next_step}")
    if snapshot.todos:
        done_count = sum(1 for todo in snapshot.todos if todo.get("status") == "done")
        pending_count = sum(1 for todo in snapshot.todos if todo.get("status") == "pending")
        body_lines.append(
            f"Completed action: {done_count} done / {len(snapshot.todos)} tracked todos."
        )
        body_lines.append(
            f"Todos: {done_count} done, {pending_count} pending."
        )
    if snapshot.acceptance_criteria:
        body_lines.append(
            f"Acceptance criteria: {len(snapshot.acceptance_criteria)} item(s)."
        )
    material_scope_changes = [
        entry.get("summary", "")
        for entry in snapshot.scope_changes
        if isinstance(entry, dict) and entry.get("material") and entry.get("summary")
    ]
    if material_scope_changes:
        body_lines.append(f"Scope change: {material_scope_changes[-1]}")
    if snapshot.changed_files:
        body_lines.append(f"Changed files: {', '.join(snapshot.changed_files)}")
    if checkpoint.get("blockers"):
        body_lines.append(f"Blockers: {checkpoint['blockers']}")
    body = "\n".join(body_lines)
    return "turn", title, body


def sync_session_artifacts(paths: SessionArtifactPaths) -> None:
    """Synchronize the session artifact files from the current task state.

    Args:
        paths: Resolved session artifact paths to update.
    """
    snapshot = collect_session_artifact_snapshot()
    try:
        write_feature_list(paths, build_feature_list_payload(snapshot))
        write_progress_note(paths, build_progress_note(snapshot))
        write_contract(paths, build_contract_note(snapshot))
        op, title, body = build_log_entry(snapshot)
        append_log_entry(paths, op, title, body)
        logger.info(
            "Synced session artifacts for session_id=%s todo_count=%d",
            getattr(config, "SESSION_ID", None),
            len(snapshot.todos),
        )
    except Exception:
        logger.exception("Failed to sync session artifacts")
