from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from monitor._stubs import appdirs

SESSION_ARTIFACT_FILENAMES = (
    "feature_list.json",
    "progress.md",
    "contract.md",
    "log.md",
)


@dataclass(frozen=True)
class SessionArtifactPaths:
    """Resolved paths for a session artifact directory.

    Attributes:
        root: The Monitor sessions root.
        folder: The concrete per-session folder.
        feature_list: Path to feature_list.json.
        progress: Path to progress.md.
        contract: Path to contract.md.
        log: Path to log.md.
    """

    root: Path
    folder: Path
    feature_list: Path
    progress: Path
    contract: Path
    log: Path


def get_sessions_root() -> Path:
    """Return the root directory for session artifact folders.

    Returns:
        The Monitor sessions root under the user config directory.
    """
    from monitor import config

    folder_name = getattr(config, "SESSIONS_FOLDER", "sessions")
    return Path(appdirs.user_config_dir("monitor")) / folder_name


def normalize_session_identifier(session_identifier: str) -> str:
    """Return a filesystem-safe session identifier.

    Args:
        session_identifier: Raw session identifier to normalize.

    Returns:
        A sanitized identifier suitable for use in a path component.
    """
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", session_identifier.strip())
    return cleaned.strip("._-") or "session"


def build_session_folder_name(timestamp_prefix: str, session_identifier: str) -> str:
    """Build the per-session folder name.

    Args:
        timestamp_prefix: Timestamp prefix such as YYYYMMDD_HH_MM.
        session_identifier: Raw session identifier to sanitize.

    Returns:
        The folder name combining timestamp and sanitized identifier.
    """
    normalized = normalize_session_identifier(session_identifier)
    return f"{timestamp_prefix}_{normalized}"


def get_session_folder_path(timestamp_prefix: str, session_identifier: str) -> Path:
    """Return the absolute path for a session folder.

    Args:
        timestamp_prefix: Timestamp prefix for the folder.
        session_identifier: Raw session identifier to sanitize.

    Returns:
        Absolute path to the session folder.
    """
    return get_sessions_root() / build_session_folder_name(timestamp_prefix, session_identifier)


def get_latest_session_folder_path(session_identifier: str) -> Path | None:
    """Return the newest on-disk session folder for a session identifier.

    Args:
        session_identifier: Session identifier to match in folder names.

    Returns:
        The newest matching session folder, or ``None`` if none exist.
    """
    normalized = normalize_session_identifier(session_identifier)
    folders = [
        folder
        for folder in list_session_folders()
        if folder.name.endswith(f"_{normalized}")
    ]
    if not folders:
        return None
    return folders[-1]


def resolve_session_artifact_paths(timestamp_prefix: str, session_identifier: str) -> SessionArtifactPaths:
    """Resolve all artifact paths for a session.

    Args:
        timestamp_prefix: Timestamp prefix for the folder.
        session_identifier: Raw session identifier to sanitize.

    Returns:
        A dataclass containing the resolved artifact paths.
    """
    root = get_sessions_root()
    folder = get_session_folder_path(timestamp_prefix, session_identifier)
    return SessionArtifactPaths(
        root=root,
        folder=folder,
        feature_list=folder / "feature_list.json",
        progress=folder / "progress.md",
        contract=folder / "contract.md",
        log=folder / "log.md",
    )


def ensure_session_folder(timestamp_prefix: str, session_identifier: str) -> SessionArtifactPaths:
    """Ensure the session folder exists and return its resolved paths.

    Args:
        timestamp_prefix: Timestamp prefix for the folder.
        session_identifier: Raw session identifier to sanitize.

    Returns:
        Resolved session artifact paths.
    """
    paths = resolve_session_artifact_paths(timestamp_prefix, session_identifier)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.folder.mkdir(parents=True, exist_ok=True)
    return paths


def _write_text(path: Path, content: str, *, append: bool = False) -> None:
    """Write text to a path, optionally appending.

    Args:
        path: Target path.
        content: Text to write.
        append: When True, append to the file instead of replacing it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as file_handle:
        file_handle.write(content)


def _write_text_if_missing(path: Path, content: str) -> bool:
    """Write text to a path only if the file does not already exist.

    Args:
        path: Target path.
        content: Text to write when the file is missing.

    Returns:
        True if the file was created and written, otherwise False.
    """
    if path.exists():
        return False
    _write_text(path, content)
    return True


def write_feature_list(paths: SessionArtifactPaths, payload: dict[str, Any]) -> None:
    """Write the session feature list payload.

    Args:
        paths: Resolved session artifact paths.
        payload: Structured session plan data.
    """
    _write_text(paths.feature_list, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_progress_note(paths: SessionArtifactPaths, content: str) -> None:
    """Write the session progress note.

    Args:
        paths: Resolved session artifact paths.
        content: Markdown content to write.
    """
    _write_text(paths.progress, content.rstrip() + "\n")


def write_contract(paths: SessionArtifactPaths, content: str) -> None:
    """Write the session contract note.

    Args:
        paths: Resolved session artifact paths.
        content: Markdown content to write.
    """
    _write_text(paths.contract, content.rstrip() + "\n")


def append_log_entry(paths: SessionArtifactPaths, op: str, title: str, body: str = "") -> None:
    """Append one log entry to the session log.

    Args:
        paths: Resolved session artifact paths.
        op: Short operation label.
        title: Entry title.
        body: Optional body text.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"## [{today}] {op} | {title}".rstrip()]
    body_text = body.rstrip()
    if body_text:
        lines.extend([body_text, ""])
    else:
        lines.append("")
    _write_text(paths.log, "\n".join(lines) + "\n", append=True)


def seed_session_artifacts(paths: SessionArtifactPaths, session_id: str) -> None:
    """Seed initial session artifact files without overwriting existing content.

    Args:
        paths: Resolved session artifact paths.
        session_id: Session identifier to record in seeded content.
    """
    _write_text_if_missing(
        paths.feature_list,
        json.dumps(
            {
                "features": [],
                "session_id": session_id,
                "status": "active",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    _write_text_if_missing(
        paths.progress,
        "# Session Progress\n\nSession started. Track progress updates here.\n",
    )
    _write_text_if_missing(
        paths.contract,
        (
            "# Session Contract\n\n"
            "- Maintain the contract as requirements evolve.\n"
            "- Keep the progress note updated with meaningful milestones.\n"
            "- Track planned and completed work in the feature list.\n"
            "- Append important events and decisions to the log.\n"
        ),
    )
    if _write_text_if_missing(paths.log, ""):
        append_log_entry(paths, "startup", "Session started")


def list_session_folders() -> list[Path]:
    """Return all session folders sorted newest-last.

    Returns:
        A list of existing session folders sorted lexicographically.
    """
    root = get_sessions_root()
    if not root.exists():
        return []
    folders = [entry for entry in root.iterdir() if entry.is_dir()]
    return sorted(folders)


def list_most_recent_session_folders(limit: int = 5) -> list[Path]:
    """Return the most recent session folders newest-first.

    Args:
        limit: Maximum number of folders to return.

    Returns:
        A list of the newest session folders, capped at ``limit``.
    """
    folders = list_session_folders()
    if not folders:
        return []
    return list(reversed(folders[-limit:]))


def get_most_recent_session_folder() -> Path | None:
    """Return the newest session folder by lexicographic sort.

    Returns:
        The most recent session folder, or ``None`` if no folders exist.
    """
    folders = list_session_folders()
    if not folders:
        return None
    return folders[-1]
