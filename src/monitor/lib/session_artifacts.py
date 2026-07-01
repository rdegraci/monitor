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
    return Path(appdirs.user_config_dir("monitor")) / "sessions"


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
