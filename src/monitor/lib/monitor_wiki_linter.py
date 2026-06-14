"""Deterministic structural linting for Monitor project wiki content."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_INDEX_NAME = "INDEX.md"

_LATEST_WIKI_LINT_RESULT: dict[str, Any] | None = None
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
_SEMANTIC_LOCATION_CLAIM_PATTERN = re.compile(
    r"\b(lives in|implemented in|defined in|authoritative implementation)\b",
    re.IGNORECASE,
)
_SEMANTIC_AUTHORITY_CLAIM_PATTERN = re.compile(
    r"\b(authoritative doc|source of truth|canonical guide|official guide)\b",
    re.IGNORECASE,
)
_SEMANTIC_WORKFLOW_CLAIM_PATTERN = re.compile(
    r"\b(instructions live in|documented in|build steps are in|test workflow is in)\b",
    re.IGNORECASE,
)
_SEMANTIC_OWNERSHIP_CLAIM_PATTERN = re.compile(
    r"\b(owned by|ownership lives in|routing lives in|changes belong in|handled in)\b",
    re.IGNORECASE,
)


def _finding(
    *,
    kind: str,
    severity: str,
    page: str,
    path: str,
    message: str,
    suggestion: str,
) -> dict[str, str]:
    """Build a structured lint finding dictionary.

    Args:
        kind: Stable finding kind identifier.
        severity: Severity label for the finding.
        page: Markdown page associated with the finding.
        path: Referenced page or repo-relative path associated with the finding.
        message: Human-readable finding description.
        suggestion: Human-readable remediation guidance.

    Returns:
        A structured finding dictionary with consistent keys and string values.
    """
    return {
        "kind": kind,
        "severity": severity,
        "page": page,
        "path": path,
        "message": message,
        "suggestion": suggestion,
    }


def _finding_id(finding: dict[str, Any]) -> str:
    """Build a stable identifier for a wiki-lint finding.

    Args:
        finding: Finding dictionary containing stable identifying fields.

    Returns:
        A stable string identifier derived from the finding content.
    """
    kind = str(finding.get("kind", ""))
    page = str(finding.get("page", ""))
    path = str(finding.get("path", ""))
    claim = str(finding.get("claim", ""))
    return "|".join([kind, page, path, claim])


def _attach_finding_ids(result: dict[str, Any]) -> dict[str, Any]:
    """Attach stable finding identifiers to a wiki-lint result.

    Args:
        result: Wiki-lint result dictionary.

    Returns:
        The same result dictionary with ``id`` fields attached to each finding.
    """
    findings = result.get("findings", [])
    if isinstance(findings, list):
        for finding in findings:
            if isinstance(finding, dict):
                finding["id"] = _finding_id(finding)

    structural = result.get("structural")
    if isinstance(structural, dict):
        _attach_finding_ids(structural)

    semantic = result.get("semantic")
    if isinstance(semantic, dict):
        _attach_finding_ids(semantic)

    return result


def store_latest_wiki_lint_result(result: dict[str, Any]) -> dict[str, Any]:
    """Store the latest wiki-lint result for later fix workflows.

    Args:
        result: Wiki-lint result dictionary to store.

    Returns:
        The stored wiki-lint result with finding identifiers attached.
    """
    global _LATEST_WIKI_LINT_RESULT

    stored_result = _attach_finding_ids(result)
    _LATEST_WIKI_LINT_RESULT = stored_result
    return stored_result


def latest_wiki_lint_result() -> dict[str, Any] | None:
    """Return the latest stored wiki-lint result.

    Returns:
        The latest stored wiki-lint result, or ``None`` if no lint run has been
        stored in the current process.
    """
    return _LATEST_WIKI_LINT_RESULT


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
    return list(referenced_repo_paths_with_pages(project_dir))


def referenced_repo_paths_with_pages(project_dir: Path) -> dict[str, str]:
    """Return repo-relative paths mapped to the first wiki page that referenced them.

    Args:
        project_dir: Project wiki directory containing markdown pages.

    Returns:
        A dictionary whose keys are de-duplicated repo-relative paths referenced
        anywhere in the wiki markdown files and whose values are the markdown
        page names where each path was first referenced, in wiki index order
        and then alphabetical page order.
    """
    if not project_dir.is_dir():
        return {}

    ordered_page_names = [_INDEX_NAME] if (project_dir / _INDEX_NAME).is_file() else []
    ordered_page_names.extend(
        page_name
        for page_name in markdown_pages_in_project_wiki(project_dir)
        if page_name != _INDEX_NAME
    )

    referenced_paths: dict[str, str] = {}
    for page_name in ordered_page_names:
        page_path = project_dir / page_name
        for match in _REPO_PATH_REFERENCE_PATTERN.findall(page_path.read_text(encoding="utf-8")):
            if match in referenced_paths:
                continue
            referenced_paths[match] = page_name
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


def semantic_location_claims(project_dir: Path) -> list[dict[str, str]]:
    """Extract claim-bearing wiki sentences that assert implementation locations.

    Args:
        project_dir: Project wiki directory containing markdown pages.

    Returns:
        A list of dictionaries describing semantic location claims found in wiki
        pages. Each dictionary contains ``page``, ``claim``, and ``path``.
    """
    claims: list[dict[str, str]] = []
    for page_name in markdown_pages_in_project_wiki(project_dir):
        page_path = project_dir / page_name
        page_text = page_path.read_text(encoding="utf-8")
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _SEMANTIC_LOCATION_CLAIM_PATTERN.search(line) is None:
                continue
            repo_paths = _REPO_PATH_REFERENCE_PATTERN.findall(line)
            if not repo_paths:
                continue
            for repo_path in repo_paths:
                claims.append(
                    {
                        "page": page_name,
                        "claim": line,
                        "path": repo_path,
                    }
                )
    return claims


def semantic_authority_claims(project_dir: Path) -> list[dict[str, str]]:
    """Extract claim-bearing wiki sentences that assert authoritative docs.

    Args:
        project_dir: Project wiki directory containing markdown pages.

    Returns:
        A list of dictionaries describing semantic authority claims found in
        wiki pages. Each dictionary contains ``page``, ``claim``, and ``path``.
    """
    claims: list[dict[str, str]] = []
    for page_name in markdown_pages_in_project_wiki(project_dir):
        page_path = project_dir / page_name
        page_text = page_path.read_text(encoding="utf-8")
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _SEMANTIC_AUTHORITY_CLAIM_PATTERN.search(line) is None:
                continue
            repo_paths = _REPO_PATH_REFERENCE_PATTERN.findall(line)
            if not repo_paths:
                continue
            for repo_path in repo_paths:
                claims.append(
                    {
                        "page": page_name,
                        "claim": line,
                        "path": repo_path,
                    }
                )
    return claims


def semantic_workflow_claims(project_dir: Path) -> list[dict[str, str]]:
    """Extract claim-bearing wiki sentences that assert workflow doc locations.

    Args:
        project_dir: Project wiki directory containing markdown pages.

    Returns:
        A list of dictionaries describing semantic workflow claims found in wiki
        pages. Each dictionary contains ``page``, ``claim``, and ``path``.
    """
    claims: list[dict[str, str]] = []
    for page_name in markdown_pages_in_project_wiki(project_dir):
        page_path = project_dir / page_name
        page_text = page_path.read_text(encoding="utf-8")
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _SEMANTIC_WORKFLOW_CLAIM_PATTERN.search(line) is None:
                continue
            repo_paths = _REPO_PATH_REFERENCE_PATTERN.findall(line)
            if not repo_paths:
                continue
            for repo_path in repo_paths:
                claims.append(
                    {
                        "page": page_name,
                        "claim": line,
                        "path": repo_path,
                    }
                )
    return claims


def semantic_ownership_claims(project_dir: Path) -> list[dict[str, str]]:
    """Extract claim-bearing wiki sentences that assert ownership or routing.

    Args:
        project_dir: Project wiki directory containing markdown pages.

    Returns:
        A list of dictionaries describing semantic ownership claims found in
        wiki pages. Each dictionary contains ``page``, ``claim``, and ``path``.
    """
    claims: list[dict[str, str]] = []
    for page_name in markdown_pages_in_project_wiki(project_dir):
        page_path = project_dir / page_name
        page_text = page_path.read_text(encoding="utf-8")
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _SEMANTIC_OWNERSHIP_CLAIM_PATTERN.search(line) is None:
                continue
            repo_paths = _REPO_PATH_REFERENCE_PATTERN.findall(line)
            if not repo_paths:
                continue
            for repo_path in repo_paths:
                claims.append(
                    {
                        "page": page_name,
                        "claim": line,
                        "path": repo_path,
                    }
                )
    return claims


def lint_project_wiki(project_dir: Path, repo_root: Path | None = None) -> dict[str, Any]:
    """Run structural lint checks for a project wiki directory.

    Args:
        project_dir: Project wiki directory to lint.
        repo_root: Repository root used to resolve repo-relative path
            references. When ``None``, falls back to ``project_dir.parent.parent``
            for backward compatibility with in-repo wiki layouts; production
            callers should pass the frozen project identity path because the
            wiki lives under appdir, not under the repository.

    Returns:
        A dictionary containing the lint result with these keys:
        ``ok`` (bool), ``project_dir`` (str), ``missing_index`` (bool),
        ``broken_references`` (list[str]), ``missing_repo_paths`` (list[str]),
        ``oversized_pages`` (list[str]), ``low_signal_pages`` (list[str]),
        ``orphaned_pages`` (list[str]), and ``findings``
        (list[dict[str, str]]). Each finding dictionary contains the fields
        ``kind``, ``severity``, ``page``, ``path``, ``message``, and
        ``suggestion``.
    """
    repo_root = Path(repo_root) if repo_root is not None else project_dir.parent.parent
    index_path = project_dir / _INDEX_NAME
    missing_index = not index_path.is_file()
    referenced_pages = referenced_wiki_pages(index_path)
    referenced_path_pages = referenced_repo_paths_with_pages(project_dir)
    referenced_paths = list(referenced_path_pages)
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
            _finding(
                kind="missing_index",
                severity="warning",
                page=_INDEX_NAME,
                path=_INDEX_NAME,
                message="Project wiki directory exists but INDEX.md is missing.",
                suggestion="Add INDEX.md to the project wiki directory.",
            )
        )
    for page_name in broken_references:
        findings.append(
            _finding(
                kind="broken_reference",
                severity="warning",
                page=_INDEX_NAME,
                path=page_name,
                message=f"INDEX.md references missing page: {page_name}",
                suggestion=f"Create {page_name} or remove its reference from INDEX.md.",
            )
        )
    for repo_path in missing_repo_paths:
        findings.append(
            _finding(
                kind="missing_repo_path",
                severity="warning",
                page=referenced_path_pages.get(repo_path, ""),
                path=repo_path,
                message=f"Wiki references missing repo path: {repo_path}",
                suggestion=f"Create {repo_path} or update the wiki reference.",
            )
        )
    for page_name in oversized_pages:
        findings.append(
            _finding(
                kind="oversized_page",
                severity="info",
                page=page_name,
                path=page_name,
                message=f"Wiki page exceeds size heuristic thresholds: {page_name}",
                suggestion="Consider splitting the page into smaller focused pages.",
            )
        )
    for page_name in low_signal_pages:
        findings.append(
            _finding(
                kind="low_signal_page",
                severity="info",
                page=page_name,
                path=page_name,
                message=f"Wiki page appears low-signal for its size: {page_name}",
                suggestion="Add structure, references, or actionable detail to the page.",
            )
        )
    for page_name in orphaned_pages:
        findings.append(
            _finding(
                kind="orphaned_page",
                severity="info",
                page=page_name,
                path=page_name,
                message=f"Wiki page is not referenced from INDEX.md: {page_name}",
                suggestion=f"Reference {page_name} from INDEX.md or remove the page.",
            )
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


def format_wiki_lint_report(result: dict[str, Any]) -> str:
    """Format a human-readable report for a wiki lint result.

    Args:
        result: Wiki lint result dictionary produced by ``lint_project_wiki``.

    Returns:
        A stable, human-readable text report that summarizes the lint outcome
        and renders findings grouped by severity.
    """
    ok = bool(result.get("ok"))
    findings = result.get("findings", [])
    project_dir = str(result.get("project_dir", ""))

    lines = [f"Wiki lint: {'PASS' if ok else 'FAIL'}", f"Project wiki: {project_dir}"]

    if not findings:
        lines.append("No findings. Wiki structure looks good.")
        return "\n".join(lines)

    warning_count = sum(1 for finding in findings if finding.get("severity") == "warning")
    info_count = sum(1 for finding in findings if finding.get("severity") == "info")
    lines.append(f"Findings: {len(findings)} (warnings: {warning_count}, infos: {info_count})")

    severities = [str(finding.get("severity", "")) for finding in findings]
    other_severities = sorted(
        {severity for severity in severities if severity not in {"warning", "info"}}
    )

    ordered_severities: list[str] = []
    if "warning" in severities:
        ordered_severities.append("warning")
    if "info" in severities:
        ordered_severities.append("info")
    ordered_severities.extend(other_severities)

    for severity in ordered_severities:
        lines.append("")
        lines.append(f"{severity.upper()}:")
        for finding in findings:
            if finding.get("severity") != severity:
                continue
            kind = str(finding.get("kind", ""))
            page = str(finding.get("page", ""))
            path = str(finding.get("path", ""))
            message = str(finding.get("message", ""))
            suggestion = str(finding.get("suggestion", ""))

            context_parts: list[str] = []
            if page:
                context_parts.append(f"page={page}")
            if path and path != page:
                context_parts.append(f"path={path}")
            elif path and not page:
                context_parts.append(f"path={path}")

            lines.append(f"- kind: {kind}")
            if context_parts:
                lines.append(f"  context: {', '.join(context_parts)}")
            lines.append(f"  message: {message}")
            lines.append(f"  suggestion: {suggestion}")

    return "\n".join(lines)


def run_project_wiki_lint(project_dir: Path, repo_root: Path | None = None) -> dict[str, Any]:
    """Run the wiki linter and attach a formatted report.

    Args:
        project_dir: Project wiki directory to lint.
        repo_root: Repository root for resolving repo-relative references. See
            ``lint_project_wiki`` for fallback behavior.

    Returns:
        A dictionary containing the full result from ``lint_project_wiki`` plus
        a ``report`` key with the formatted text produced by
        ``format_wiki_lint_report``.
    """
    result = lint_project_wiki(project_dir, repo_root)
    report = format_wiki_lint_report(result)
    return {
        **result,
        "report": report,
    }


def run_project_wiki_structural_lint(
    project_dir: Path, repo_root: Path | None = None
) -> dict[str, Any]:
    """Run structural wiki linting and return a mode-tagged result.

    Args:
        project_dir: Project wiki directory to lint.
        repo_root: Repository root for resolving repo-relative references. See
            ``lint_project_wiki`` for fallback behavior.

    Returns:
        A structural wiki-lint result dictionary with a ``mode`` field and a
        formatted ``report``.
    """
    result = run_project_wiki_lint(project_dir, repo_root)
    return {
        **result,
        "mode": "structural",
    }


def run_project_wiki_semantic_lint(
    project_dir: Path, repo_root: Path | None = None
) -> dict[str, Any]:
    """Run narrow semantic wiki linting for stale path-grounded claims.

    Args:
        project_dir: Project wiki directory to lint.
        repo_root: Repository root for resolving repo-relative references. See
            ``lint_project_wiki`` for fallback behavior.

    Returns:
        A semantic wiki-lint result dictionary. The current implementation is a
        narrow v1 that detects claim-bearing wiki sentences asserting that an
        implementation location or authoritative project-local document lives at
        a repo-relative path that no longer exists.
    """
    repo_root = Path(repo_root) if repo_root is not None else project_dir.parent.parent
    findings: list[dict[str, str]] = []
    for claim in semantic_location_claims(project_dir):
        repo_path = claim["path"]
        if (repo_root / repo_path).exists():
            continue
        findings.append(
            {
                "kind": "semantic_stale_location_claim",
                "severity": "warning",
                "page": claim["page"],
                "path": repo_path,
                "message": f"Wiki location claim references missing path: {repo_path}",
                "suggestion": "Update the wiki claim to point to the current implementation location.",
                "claim": claim["claim"],
                "evidence": repo_path,
                "impact": "This stale location claim could mislead coding work about where behavior lives.",
            }
        )

    for claim in semantic_authority_claims(project_dir):
        repo_path = claim["path"]
        if (repo_root / repo_path).exists():
            continue
        findings.append(
            {
                "kind": "semantic_stale_authority_claim",
                "severity": "warning",
                "page": claim["page"],
                "path": repo_path,
                "message": f"Wiki authority claim references missing path: {repo_path}",
                "suggestion": "Update the wiki claim to reference the current authoritative document.",
                "claim": claim["claim"],
                "evidence": repo_path,
                "impact": "This stale authority claim could mislead coding work about which document is authoritative.",
            }
        )

    for claim in semantic_workflow_claims(project_dir):
        repo_path = claim["path"]
        if (repo_root / repo_path).exists():
            continue
        findings.append(
            {
                "kind": "semantic_stale_workflow_claim",
                "severity": "warning",
                "page": claim["page"],
                "path": repo_path,
                "message": f"Wiki workflow claim references missing path: {repo_path}",
                "suggestion": "Update the wiki claim to reference the current workflow instructions.",
                "claim": claim["claim"],
                "evidence": repo_path,
                "impact": "This stale workflow claim could mislead coding work about how to build, test, or validate changes.",
            }
        )

    for claim in semantic_ownership_claims(project_dir):
        repo_path = claim["path"]
        if (repo_root / repo_path).exists():
            continue
        findings.append(
            {
                "kind": "semantic_stale_ownership_claim",
                "severity": "warning",
                "page": claim["page"],
                "path": repo_path,
                "message": f"Wiki ownership claim references missing path: {repo_path}",
                "suggestion": "Update the wiki claim to reference the current owning subsystem or routing path.",
                "claim": claim["claim"],
                "evidence": repo_path,
                "impact": "This stale ownership claim could mislead coding work about where a developer should make a change.",
            }
        )

    if findings:
        lines = [f"Wiki lint: FAIL", f"Project wiki: {project_dir}"]
        lines.append(f"Findings: {len(findings)} (warnings: {len(findings)}, infos: 0)")
        lines.append("")
        lines.append("WARNING:")
        for finding in findings:
            lines.append(f"- kind: {finding['kind']}")
            lines.append(
                f"  context: page={finding['page']}, path={finding['path']}"
            )
            lines.append(f"  claim: {finding['claim']}")
            lines.append(f"  message: {finding['message']}")
            lines.append(f"  impact: {finding['impact']}")
            lines.append(f"  suggestion: {finding['suggestion']}")
        report = "\n".join(lines)
    else:
        report = (
            f"Wiki lint: PASS\nProject wiki: {project_dir}\n"
            "No semantic findings."
        )

    return {
        "ok": not findings,
        "mode": "semantic",
        "project_dir": str(project_dir),
        "findings": findings,
        "report": report,
    }


def run_project_wiki_lint_mode(
    project_dir: Path, mode: str, repo_root: Path | None = None
) -> dict[str, Any]:
    """Run the requested wiki-lint mode.

    Args:
        project_dir: Project wiki directory to lint.
        mode: Requested lint mode. Supported values are ``structural``,
            ``semantic``, and ``all``.
        repo_root: Repository root for resolving repo-relative references. See
            ``lint_project_wiki`` for fallback behavior.

    Returns:
        A wiki-lint result dictionary for the requested mode.

    Raises:
        ValueError: If ``mode`` is unsupported.
    """
    if mode == "structural":
        return store_latest_wiki_lint_result(
            run_project_wiki_structural_lint(project_dir, repo_root)
        )

    if mode == "semantic":
        return store_latest_wiki_lint_result(
            run_project_wiki_semantic_lint(project_dir, repo_root)
        )

    if mode == "all":
        structural_result = run_project_wiki_structural_lint(project_dir, repo_root)
        semantic_result = run_project_wiki_semantic_lint(project_dir, repo_root)
        report = (
            "Wiki lint mode: all\n\n"
            "== Structural ==\n"
            f"{structural_result['report']}\n\n"
            "== Semantic ==\n"
            f"{semantic_result['report']}"
        )
        combined_result = {
            "ok": bool(structural_result.get("ok")) and bool(semantic_result.get("ok")),
            "mode": "all",
            "project_dir": str(project_dir),
            "structural": structural_result,
            "semantic": semantic_result,
            "findings": [
                *structural_result.get("findings", []),
                *semantic_result.get("findings", []),
            ],
            "report": report,
        }
        return store_latest_wiki_lint_result(combined_result)

    raise ValueError(f"Unsupported wiki lint mode: {mode}")
