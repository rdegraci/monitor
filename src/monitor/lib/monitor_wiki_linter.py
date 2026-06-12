"""Deterministic structural linting for Monitor project wiki content."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_INDEX_NAME = "INDEX.md"
_MAX_PAGE_LINES = 400
_MAX_PAGE_CHARACTERS = 20_000
_LOW_SIGNAL_MIN_LINES = 80
_LOW_SIGNAL_MAX_HEADINGS = 2
_LOW_SIGNAL_MAX_REFERENCES = 2
_LOW_SIGNAL_MAX_LIST_ITEMS = 10
_HEADING_PATTERN = re.compile(r"^#{1,6}\s", re.MULTILINE)
_LIST_ITEM_PATTERN = re.compile(r"^(?:[-*]|\d+\.)\s", re.MULTILINE)
_MARKDOWN_REFERENCE_PATTERN = re.compile(r"\b([A-Z][A-Z0-9_-]*\.md)\b")
_REPO_PATH_REFERENCE_PATTERN = re.compile(
    r"(?<![\w./-])((?:src|tests|docs)/[A-Za-z0-9_./-]+(?:\.[A-Za-z0-9_-]+)?)(?![\w./-])"
)


def referenced_wiki_pages(index_path: Path) -> list[str]:
    """Return referenced markdown page names from a wiki index file.

    Args:
        index_path: Path to the wiki ``INDEX.md`` file.

    Returns:
        A de-duplicated list of referenced markdown filenames in first-seen
        order, excluding ``INDEX.md`` itself.
    """
    if not index_path.is_file():
        return []

    seen: set[str] = set()
    pages: list[str] = []
    for match in _MARKDOWN_REFERENCE_PATTERN.findall(index_path.read_text(encoding="utf-8")):
        if match == _INDEX_NAME or match in seen:
            continue
        seen.add(match)
        pages.append(match)
    return pages


def referenced_repo_paths(project_dir: Path) -> list[str]:
    """Return repo-relative file paths referenced from wiki markdown files.

    Args:
        project_dir: Project wiki directory containing markdown pages.

    Returns:
        A de-duplicated list of repo-relative paths referenced anywhere in the
        wiki markdown files, in wiki index order and then alphabetical page
        order.
    """
    if not project_dir.is_dir():
        return []

    ordered_page_names = [_INDEX_NAME] if (project_dir / _INDEX_NAME).is_file() else []
    ordered_page_names.extend(
        page_name
        for page_name in markdown_pages_in_project_wiki(project_dir)
        if page_name != _INDEX_NAME
    )

    seen: set[str] = set()
    referenced_paths: list[str] = []
    for page_name in ordered_page_names:
        page_path = project_dir / page_name
        for match in _REPO_PATH_REFERENCE_PATTERN.findall(page_path.read_text(encoding="utf-8")):
            if match in seen:
                continue
            seen.add(match)
            referenced_paths.append(match)
    return referenced_paths


def markdown_pages_in_project_wiki(project_dir: Path) -> list[str]:
    """Return markdown page names present in a project wiki directory.

    Args:
        project_dir: Project wiki directory to inspect.

    Returns:
        A sorted list of markdown filenames directly inside ``project_dir``.
    """
    if not project_dir.is_dir():
        return []

    return sorted(
        path.name
        for path in project_dir.iterdir()
        if path.is_file() and path.suffix == ".md"
    )


def oversized_wiki_pages(project_dir: Path) -> list[str]:
    """Return markdown page names whose size exceeds heuristic thresholds.

    Args:
        project_dir: Project wiki directory containing markdown pages.

    Returns:
        A sorted list of markdown filenames whose line count or character count
        exceeds the configured heuristic thresholds.
    """
    oversized_pages: list[str] = []
    for page_name in markdown_pages_in_project_wiki(project_dir):
        if page_name == _INDEX_NAME:
            continue
        page_text = (project_dir / page_name).read_text(encoding="utf-8")
        if page_text.count("\n") + 1 > _MAX_PAGE_LINES or len(page_text) > _MAX_PAGE_CHARACTERS:
            oversized_pages.append(page_name)
    return oversized_pages


def low_signal_wiki_pages(project_dir: Path) -> list[str]:
    """Return markdown page names whose content appears low-signal.

    Args:
        project_dir: Project wiki directory containing markdown pages.

    Returns:
        A sorted list of markdown filenames whose content is large enough to
        matter but contains very few headings and very few wiki or repo-path
        references.
    """
    low_signal_pages: list[str] = []
    for page_name in markdown_pages_in_project_wiki(project_dir):
        if page_name == _INDEX_NAME:
            continue
        page_text = (project_dir / page_name).read_text(encoding="utf-8")
        if page_text.count("\n") + 1 < _LOW_SIGNAL_MIN_LINES:
            continue
        heading_count = len(_HEADING_PATTERN.findall(page_text))
        reference_count = len(_MARKDOWN_REFERENCE_PATTERN.findall(page_text))
        reference_count += len(_REPO_PATH_REFERENCE_PATTERN.findall(page_text))
        list_item_count = len(_LIST_ITEM_PATTERN.findall(page_text))
        if (
            heading_count <= _LOW_SIGNAL_MAX_HEADINGS
            and reference_count <= _LOW_SIGNAL_MAX_REFERENCES
            and list_item_count <= _LOW_SIGNAL_MAX_LIST_ITEMS
        ):
            low_signal_pages.append(page_name)
    return low_signal_pages


def lint_project_wiki(project_dir: Path) -> dict[str, Any]:
    """Run structural lint checks for a project wiki directory.

    Args:
        project_dir: Project wiki directory to lint.

    Returns:
        A dictionary containing the lint result with these keys:
        ``ok`` (bool), ``project_dir`` (str), ``missing_index`` (bool),
        ``broken_references`` (list[str]), ``missing_repo_paths`` (list[str]),
        ``oversized_pages`` (list[str]), ``low_signal_pages`` (list[str]),
        ``orphaned_pages`` (list[str]), and ``findings``
        (list[dict[str, str]]).
    """
    repo_root = project_dir.parent.parent
    index_path = project_dir / _INDEX_NAME
    missing_index = not index_path.is_file()
    referenced_pages = referenced_wiki_pages(index_path)
    referenced_paths = referenced_repo_paths(project_dir)
    markdown_pages = markdown_pages_in_project_wiki(project_dir)
    oversized_pages = oversized_wiki_pages(project_dir)
    low_signal_pages = low_signal_wiki_pages(project_dir)

    broken_references = [
        page_name
        for page_name in referenced_pages
        if not (project_dir / page_name).is_file()
    ]
    missing_repo_paths = [
        repo_path
        for repo_path in referenced_paths
        if not (repo_root / repo_path).exists()
    ]
    orphaned_pages = [
        page_name
        for page_name in markdown_pages
        if page_name != _INDEX_NAME and page_name not in referenced_pages
    ]

    findings: list[dict[str, str]] = []
    if missing_index:
        findings.append(
            {
                "kind": "missing_index",
                "message": "Project wiki directory exists but INDEX.md is missing.",
            }
        )
    for page_name in broken_references:
        findings.append(
            {
                "kind": "broken_reference",
                "message": f"INDEX.md references missing page: {page_name}",
            }
        )
    for repo_path in missing_repo_paths:
        findings.append(
            {
                "kind": "missing_repo_path",
                "message": f"Wiki references missing repo path: {repo_path}",
            }
        )
    for page_name in oversized_pages:
        findings.append(
            {
                "kind": "oversized_page",
                "message": f"Wiki page exceeds size heuristic thresholds: {page_name}",
            }
        )
    for page_name in low_signal_pages:
        findings.append(
            {
                "kind": "low_signal_page",
                "message": f"Wiki page appears low-signal for its size: {page_name}",
            }
        )
    for page_name in orphaned_pages:
        findings.append(
            {
                "kind": "orphaned_page",
                "message": f"Wiki page is not referenced from INDEX.md: {page_name}",
            }
        )

    return {
        "ok": not findings,
        "project_dir": str(project_dir),
        "missing_index": missing_index,
        "broken_references": broken_references,
        "missing_repo_paths": missing_repo_paths,
        "oversized_pages": oversized_pages,
        "low_signal_pages": low_signal_pages,
        "orphaned_pages": orphaned_pages,
        "findings": findings,
    }
