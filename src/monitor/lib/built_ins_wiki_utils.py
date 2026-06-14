"""Wiki-related helper utilities for built-in commands."""

import os
from pathlib import Path
from typing import Any

WIKI_FIX_MAX_REPLACEMENT_LINES = 3
WIKI_FIX_MAX_REPLACEMENT_CHARACTERS = 400
WIKI_FIX_MAX_DIFF_LINES = 20

WIKI_INIT_MAX_DRAFT_LINES = 120
WIKI_INIT_MAX_DRAFT_CHARACTERS = 6000

_MANIFEST_FILENAMES = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "package.json",
    "Package.swift",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
)
_README_FILENAMES = ("README.md", "README.rst", "README.txt", "README")
_ORIENTATION_TOP_LEVEL_LIMIT = 60
_ORIENTATION_MANIFEST_HEAD_LINES = 40
_ORIENTATION_README_HEAD_LINES = 30
_ORIENTATION_MAX_CHARACTERS = 8000

_LATEST_WIKI_FIX_PREVIEWS: dict[str, dict[str, Any]] = {}
_LATEST_WIKI_INIT_DRAFT: dict[str, Any] = {}


def store_latest_wiki_fix_preview(preview: dict[str, Any]) -> dict[str, Any]:
    """Store a generated wiki-fix preview for later application.

    Args:
        preview: Preview result dictionary containing at least ``finding_id``.

    Returns:
        The stored preview dictionary.
    """
    finding_id = str(preview.get("finding_id", ""))
    if finding_id:
        _LATEST_WIKI_FIX_PREVIEWS[finding_id] = preview
    return preview


def latest_wiki_fix_preview(finding_id: str) -> dict[str, Any] | None:
    """Return the latest stored wiki-fix preview for a finding id.

    Args:
        finding_id: Stable finding id associated with the preview.

    Returns:
        The stored preview dictionary, or ``None`` if no preview is stored.
    """
    return _LATEST_WIKI_FIX_PREVIEWS.get(finding_id)


def store_latest_wiki_init_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Store the latest drafted wiki INDEX.md for a later apply step.

    Args:
        draft: Draft dictionary containing at least ``index_path`` and
            ``content``.

    Returns:
        The stored draft dictionary.
    """
    global _LATEST_WIKI_INIT_DRAFT
    _LATEST_WIKI_INIT_DRAFT = dict(draft)
    return _LATEST_WIKI_INIT_DRAFT


def latest_wiki_init_draft() -> dict[str, Any] | None:
    """Return the latest stored wiki INDEX.md draft.

    Returns:
        The stored draft dictionary, or ``None`` when no draft is stored.
    """
    return _LATEST_WIKI_INIT_DRAFT or None


def _read_head(path: Path, max_lines: int) -> str:
    """Return the first ``max_lines`` lines of a text file.

    Args:
        path: File to read.
        max_lines: Maximum number of leading lines to include.

    Returns:
        The leading lines joined by newlines, with a truncation marker appended
        when the file is longer, or an empty string when the file cannot be
        read.
    """
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    head = "\n".join(lines[:max_lines])
    if len(lines) > max_lines:
        head += "\n…(truncated)"
    return head


def build_repo_orientation_context(repo_root: str | os.PathLike[str]) -> str:
    """Build a bounded, text orientation summary of a repository.

    Gathers deterministic, high-signal repository signal (top-level layout,
    manifest files, and the README head) for use as grounding context when
    drafting a project wiki ``INDEX.md``. The result is size-bounded so it does
    not balloon prompt token usage.

    Args:
        repo_root: Repository root path to summarize.

    Returns:
        A bounded plain-text orientation summary of the repository.
    """
    root = Path(repo_root)
    sections: list[str] = [f"Repository root: {root}"]

    try:
        entries = sorted(
            f"{path.name}/" if path.is_dir() else path.name
            for path in root.iterdir()
            if not path.name.startswith(".")
        )
    except OSError:
        entries = []
    if entries:
        shown = entries[:_ORIENTATION_TOP_LEVEL_LIMIT]
        listing = "\n".join(shown)
        if len(entries) > _ORIENTATION_TOP_LEVEL_LIMIT:
            listing += f"\n…(+{len(entries) - _ORIENTATION_TOP_LEVEL_LIMIT} more)"
        sections.append("Top-level entries:\n" + listing)

    for name in _MANIFEST_FILENAMES:
        manifest = root / name
        if manifest.is_file():
            head = _read_head(manifest, _ORIENTATION_MANIFEST_HEAD_LINES)
            if head:
                sections.append(f"--- {name} ---\n{head}")

    for name in _README_FILENAMES:
        readme = root / name
        if readme.is_file():
            head = _read_head(readme, _ORIENTATION_README_HEAD_LINES)
            if head:
                sections.append(f"--- {name} ---\n{head}")
            break

    context = "\n\n".join(sections)
    if len(context) > _ORIENTATION_MAX_CHARACTERS:
        context = context[:_ORIENTATION_MAX_CHARACTERS] + "\n…(truncated)"
    return context


def wiki_fix_diff_line_count(diff_text: str) -> int:
    """Count changed diff lines in a unified diff.

    Args:
        diff_text: Unified diff text.

    Returns:
        The number of changed lines excluding file headers and hunk markers.
    """
    return sum(
        1
        for line in diff_text.splitlines()
        if (line.startswith("+") and not line.startswith("+++"))
        or (line.startswith("-") and not line.startswith("---"))
    )
