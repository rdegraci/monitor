"""Helpers for Monitor-managed project wiki paths and provisioning."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import List

from monitor._stubs import appdirs

logger = logging.getLogger(__name__)

_STARTER_INDEX_TEMPLATE = """# Project Wiki Index

## Overview
- Add a short project summary here.

## Architecture
- Add durable subsystem or boundary notes here.

## Conventions
- Add project-specific coding or workflow conventions here.

## Pitfalls
- Add durable gotchas worth remembering here.
"""
_STARTER_INDEX_NORMALIZED = _STARTER_INDEX_TEMPLATE.strip()


def nearest_repo_root(start_path: str | os.PathLike[str]) -> Path | None:
    """Return the nearest repository root for a startup path.

    Args:
        start_path: Path captured at startup.

    Returns:
        The nearest ancestor directory containing a ``.git`` entry, or ``None``
        when the path is not inside a git repository.
    """
    current = Path(start_path).resolve()
    if current.is_file():
        current = current.parent

    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def resolve_project_identity_path(start_path: str | os.PathLike[str]) -> Path:
    """Resolve the canonical project identity path for monitor-wiki use.

    Args:
        start_path: Path captured at startup.

    Returns:
        The canonical repository root when inside a git repository, otherwise the
        canonical startup directory.
    """
    startup_path = Path(start_path).resolve()
    if startup_path.is_file():
        startup_path = startup_path.parent

    repo_root = nearest_repo_root(startup_path)
    if repo_root is not None:
        return repo_root.resolve()
    return startup_path


def project_slug_from_path(project_path: str | os.PathLike[str]) -> str:
    """Convert a project identity path into a stable monitor-wiki slug.

    Args:
        project_path: Canonical project identity path.

    Returns:
        A lowercase path-derived slug suitable for use as a directory name.
    """
    canonical = str(Path(project_path).resolve()).lower()
    normalized = canonical.replace(os.sep, "-").replace(" ", "-")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized or "project"


def monitor_wiki_root() -> Path:
    """Return the appdir monitor-wiki root path.

    Returns:
        The root directory under appdir where Monitor stores project wiki data.
    """
    return Path(appdirs.user_config_dir("monitor")) / "monitor-wiki"


def project_wiki_dir_for_start_path(start_path: str | os.PathLike[str]) -> Path:
    """Return the per-project wiki directory for a startup path.

    Args:
        start_path: Path captured at startup.

    Returns:
        The project-specific wiki directory under ``monitor-wiki``.
    """
    project_path = resolve_project_identity_path(start_path)
    return monitor_wiki_root() / project_slug_from_path(project_path)


def _starter_index_path(project_dir: Path) -> Path:
    """Return the starter index path for a project wiki directory.

    Args:
        project_dir: Project wiki directory path.

    Returns:
        The ``INDEX.md`` path inside the project wiki directory.
    """
    return project_dir / "INDEX.md"


def _provision_project_wiki_dir(project_dir: Path) -> Path | None:
    """Create a project wiki directory and starter index when possible.

    Args:
        project_dir: The project wiki directory to provision.

    Returns:
        The provisioned project wiki directory, or ``None`` when filesystem
        setup fails.
    """
    try:
        project_dir.mkdir(parents=True, exist_ok=True)

        index_path = _starter_index_path(project_dir)
        if not index_path.exists():
            index_path.write_text(_STARTER_INDEX_TEMPLATE, encoding="utf-8")
    except OSError as error:
        logger.warning(
            "Monitor wiki provisioning unavailable for %s: %s",
            project_dir,
            error,
        )
        return None

    return project_dir


def ensure_project_wiki(start_path: str | os.PathLike[str]) -> Path | None:
    """Create the project wiki directory and starter index if needed.

    Args:
        start_path: Path captured at startup.

    Returns:
        The provisioned project wiki directory path, or ``None`` when
        provisioning fails.
    """
    project_dir = project_wiki_dir_for_start_path(start_path)
    return _provision_project_wiki_dir(project_dir)


def ensure_configured_project_wiki() -> Path | None:
    """Provision the frozen session project wiki, if one is configured.

    Returns:
        The provisioned project wiki directory path, or ``None`` when the
        session does not currently have frozen wiki context or provisioning
        fails.
    """
    from monitor import config as _config

    project_wiki_path = getattr(_config, "PROJECT_WIKI_PATH", None)
    if not project_wiki_path:
        return None

    project_dir = Path(project_wiki_path)
    return _provision_project_wiki_dir(project_dir)


def configured_project_wiki_index_path() -> Path | None:
    """Return the starter index path for the frozen session wiki context.

    Returns:
        The configured ``INDEX.md`` path, or ``None`` when no frozen wiki
        context exists for the session.
    """
    from monitor import config as _config

    project_wiki_path = getattr(_config, "PROJECT_WIKI_PATH", None)
    if not project_wiki_path:
        return None
    return _starter_index_path(Path(project_wiki_path))


def has_substantive_configured_project_wiki() -> bool:
    """Return whether the frozen session wiki has substantive content.

    Returns:
        ``True`` when the configured wiki has an ``INDEX.md`` whose content
        differs meaningfully from the starter template, otherwise ``False``.
    """
    index_path = configured_project_wiki_index_path()
    if index_path is None or not index_path.is_file():
        return False

    content = index_path.read_text(encoding="utf-8").strip()
    if not content:
        return False
    return content != _STARTER_INDEX_NORMALIZED


def configured_project_wiki_additional_pages(max_pages: int = 2) -> List[Path]:
    """Return up to ``max_pages`` additional wiki pages referenced by INDEX.

    Args:
        max_pages: Maximum number of additional pages to return.

    Returns:
        A list of existing markdown pages referenced from the configured
        substantive ``INDEX.md``.
    """
    index_path = configured_project_wiki_index_path()
    if index_path is None or not index_path.is_file():
        return []
    if not has_substantive_configured_project_wiki():
        return []

    matches = re.findall(r"\b([A-Z][A-Z0-9_-]*\.md)\b", index_path.read_text(encoding="utf-8"))
    pages: List[Path] = []
    seen = set()
    for match in matches:
        if match == "INDEX.md" or match in seen:
            continue
        candidate = index_path.parent / match
        if candidate.is_file():
            pages.append(candidate)
            seen.add(match)
        if len(pages) >= max_pages:
            break
    return pages


def configure_project_wiki_paths(start_path: str | os.PathLike[str] | None) -> None:
    """Resolve and cache frozen project wiki context for the session.

    Args:
        start_path: Path captured at startup, or ``None`` to clear cached state.
    """
    from monitor import config as _config

    if start_path is None:
        _config.PROJECT_WIKI_PATH = None
        _config.PROJECT_WIKI_IDENTITY_PATH = None
        return

    project_identity_path = resolve_project_identity_path(start_path)
    _config.PROJECT_WIKI_IDENTITY_PATH = str(project_identity_path)
    _config.PROJECT_WIKI_PATH = str(project_wiki_dir_for_start_path(start_path))
