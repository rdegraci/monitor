"""Tests for the structural monitor wiki linter."""

from pathlib import Path

import pytest

from monitor.lib.monitor_wiki_linter import (
    format_wiki_lint_report,
    latest_wiki_lint_result,
    lint_project_wiki,
    low_signal_wiki_pages,
    markdown_pages_in_project_wiki,
    oversized_wiki_pages,
    referenced_repo_paths,
    referenced_wiki_pages,
    run_project_wiki_lint,
    semantic_authority_claims,
    semantic_location_claims,
    semantic_workflow_claims,
    store_latest_wiki_lint_result,
)

def test_referenced_wiki_pages_returns_unique_non_index_entries(tmp_path):
    index_path = tmp_path / "INDEX.md"
    index_path.write_text(
        "See ARCHITECTURE.md and CONVENTIONS.md and ARCHITECTURE.md and INDEX.md\n",
        encoding="utf-8",
    )

    assert referenced_wiki_pages(index_path) == ["ARCHITECTURE.md", "CONVENTIONS.md"]


def test_referenced_repo_paths_returns_unique_repo_relative_matches(tmp_path):
    (tmp_path / "INDEX.md").write_text(
        "See src/monitor/lib/system_prompt.py and docs/ARCHITECTURE.md and src/monitor/lib/system_prompt.py\n",
        encoding="utf-8",
    )
    (tmp_path / "ARCHITECTURE.md").write_text(
        "Tests live in tests/monitor/lib/test_monitor_wiki_linter.py\n",
        encoding="utf-8",
    )

    assert referenced_repo_paths(tmp_path) == [
        "src/monitor/lib/system_prompt.py",
        "docs/ARCHITECTURE.md",
        "tests/monitor/lib/test_monitor_wiki_linter.py",
    ]


def test_markdown_pages_in_project_wiki_lists_direct_markdown_files(tmp_path):
    (tmp_path / "INDEX.md").write_text("index\n", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text("architecture\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not markdown\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "NESTED.md").write_text("nested\n", encoding="utf-8")

    assert markdown_pages_in_project_wiki(tmp_path) == ["ARCHITECTURE.md", "INDEX.md"]


def test_oversized_wiki_pages_reports_pages_exceeding_size_thresholds(tmp_path):
    (tmp_path / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text("line\n" * 401, encoding="utf-8")
    (tmp_path / "CONVENTIONS.md").write_text("short\n", encoding="utf-8")

    assert oversized_wiki_pages(tmp_path) == ["ARCHITECTURE.md"]


def test_low_signal_wiki_pages_reports_large_pages_with_few_signals(tmp_path):
    (tmp_path / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text(
        ("Plain paragraph with no structure.\n" * 85), encoding="utf-8"
    )
    (tmp_path / "CONVENTIONS.md").write_text(
        "# Conventions\n## Structure\n### References\nSee src/monitor/lib/system_prompt.py and ARCHITECTURE.md\n"
        + ("Useful details.\n" * 85),
        encoding="utf-8",
    )

    assert low_signal_wiki_pages(tmp_path) == ["ARCHITECTURE.md"]


def test_semantic_location_claims_extracts_claim_lines_with_repo_paths(tmp_path):
    (tmp_path / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text(
        "The authoritative implementation lives in src/monitor/lib/server.py\n"
        "This line mentions src/monitor/lib/git.py but does not make a claim.\n",
        encoding="utf-8",
    )

    assert semantic_location_claims(tmp_path) == [
        {
            "page": "ARCHITECTURE.md",
            "claim": "The authoritative implementation lives in src/monitor/lib/server.py",
            "path": "src/monitor/lib/server.py",
        }
    ]


def test_semantic_authority_claims_extracts_claim_lines_with_repo_paths(tmp_path):
    (tmp_path / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text(
        "The canonical guide is docs/process/current.md\n"
        "This line mentions docs/process/other.md but does not make a claim.\n",
        encoding="utf-8",
    )

    assert semantic_authority_claims(tmp_path) == [
        {
            "page": "ARCHITECTURE.md",
            "claim": "The canonical guide is docs/process/current.md",
            "path": "docs/process/current.md",
        }
    ]


def test_semantic_workflow_claims_extracts_claim_lines_with_repo_paths(tmp_path):
    (tmp_path / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text(
        "Build steps are in docs/build/current.md\n"
        "This line mentions docs/build/other.md but does not make a claim.\n",
        encoding="utf-8",
    )

    assert semantic_workflow_claims(tmp_path) == [
        {
            "page": "ARCHITECTURE.md",
            "claim": "Build steps are in docs/build/current.md",
            "path": "docs/build/current.md",
        }
    ]


def test_lint_project_wiki_reports_missing_index(tmp_path):
    (tmp_path / "ARCHITECTURE.md").write_text("architecture\n", encoding="utf-8")

    result = lint_project_wiki(tmp_path)

    assert result["ok"] is False
    assert result["missing_index"] is True
    assert result["broken_references"] == []
    assert result["missing_repo_paths"] == []
    assert result["oversized_pages"] == []
    assert result["low_signal_pages"] == []
    assert result["orphaned_pages"] == ["ARCHITECTURE.md"]
    assert any(finding["kind"] == "missing_index" for finding in result["findings"])

    missing_index_finding = next(
        finding for finding in result["findings"] if finding["kind"] == "missing_index"
    )
    assert missing_index_finding["kind"] == "missing_index"
    assert missing_index_finding["severity"] == "warning"
    assert missing_index_finding["page"] == "INDEX.md"
    assert missing_index_finding["path"] == "INDEX.md"
    assert missing_index_finding["message"]
    assert missing_index_finding["suggestion"]


def test_lint_project_wiki_reports_broken_references(tmp_path):
    (tmp_path / "INDEX.md").write_text(
        "See ARCHITECTURE.md and TESTING.md\n",
        encoding="utf-8",
    )
    (tmp_path / "ARCHITECTURE.md").write_text("architecture\n", encoding="utf-8")

    result = lint_project_wiki(tmp_path)

    assert result["ok"] is False
    assert result["missing_index"] is False
    assert result["broken_references"] == ["TESTING.md"]
    assert result["missing_repo_paths"] == []
    assert result["oversized_pages"] == []
    assert result["low_signal_pages"] == []
    assert any(finding["kind"] == "broken_reference" for finding in result["findings"])

    broken_reference_finding = next(
        finding
        for finding in result["findings"]
        if finding["kind"] == "broken_reference"
    )
    assert broken_reference_finding["kind"] == "broken_reference"
    assert broken_reference_finding["severity"] == "warning"
    assert broken_reference_finding["page"] == "INDEX.md"
    assert broken_reference_finding["path"] == "TESTING.md"
    assert broken_reference_finding["message"]
    assert broken_reference_finding["suggestion"]


def test_lint_project_wiki_reports_missing_repo_paths(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    (repo_root / "src").mkdir()
    (repo_root / "src" / "existing.py").write_text("print('ok')\n", encoding="utf-8")
    (wiki_dir / "INDEX.md").write_text(
        "See src/existing.py and src/missing.py and ARCHITECTURE.md\n",
        encoding="utf-8",
    )
    (wiki_dir / "ARCHITECTURE.md").write_text(
        "Also see tests/missing_test.py\n",
        encoding="utf-8",
    )

    result = lint_project_wiki(wiki_dir)

    assert result["ok"] is False
    assert result["missing_repo_paths"] == ["src/missing.py", "tests/missing_test.py"]
    assert result["oversized_pages"] == []
    assert result["low_signal_pages"] == []
    assert any(finding["kind"] == "missing_repo_path" for finding in result["findings"])

    missing_repo_path_finding = next(
        finding
        for finding in result["findings"]
        if finding["kind"] == "missing_repo_path" and finding["path"] == "src/missing.py"
    )
    assert missing_repo_path_finding["kind"] == "missing_repo_path"
    assert missing_repo_path_finding["severity"] == "warning"
    assert missing_repo_path_finding["page"] == "INDEX.md"
    assert missing_repo_path_finding["path"] == "src/missing.py"
    assert missing_repo_path_finding["message"]
    assert missing_repo_path_finding["suggestion"]


def test_lint_project_wiki_reports_low_signal_pages(tmp_path):
    (tmp_path / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text(
        ("Plain paragraph with no structure.\n" * 85), encoding="utf-8"
    )

    result = lint_project_wiki(tmp_path)

    assert result["ok"] is False
    assert result["missing_repo_paths"] == []
    assert result["oversized_pages"] == []
    assert result["low_signal_pages"] == ["ARCHITECTURE.md"]
    assert any(finding["kind"] == "low_signal_page" for finding in result["findings"])

    low_signal_finding = next(
        finding for finding in result["findings"] if finding["kind"] == "low_signal_page"
    )
    assert low_signal_finding["kind"] == "low_signal_page"
    assert low_signal_finding["severity"] == "info"
    assert low_signal_finding["page"] == "ARCHITECTURE.md"
    assert low_signal_finding["path"] == "ARCHITECTURE.md"
    assert low_signal_finding["message"]
    assert low_signal_finding["suggestion"]


def test_lint_project_wiki_reports_oversized_pages(tmp_path):
    (tmp_path / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text("- line\n" * 401, encoding="utf-8")

    result = lint_project_wiki(tmp_path)

    assert result["ok"] is False
    assert result["missing_repo_paths"] == []
    assert result["oversized_pages"] == ["ARCHITECTURE.md"]
    assert result["low_signal_pages"] == []
    assert any(finding["kind"] == "oversized_page" for finding in result["findings"])

    oversized_finding = next(
        finding for finding in result["findings"] if finding["kind"] == "oversized_page"
    )
    assert oversized_finding["kind"] == "oversized_page"
    assert oversized_finding["severity"] == "info"
    assert oversized_finding["page"] == "ARCHITECTURE.md"
    assert oversized_finding["path"] == "ARCHITECTURE.md"
    assert oversized_finding["message"]
    assert oversized_finding["suggestion"]


def test_lint_project_wiki_reports_orphaned_pages(tmp_path):
    (tmp_path / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text("architecture\n", encoding="utf-8")
    (tmp_path / "PITFALLS.md").write_text("pitfalls\n", encoding="utf-8")

    result = lint_project_wiki(tmp_path)

    assert result["ok"] is False
    assert result["missing_repo_paths"] == []
    assert result["oversized_pages"] == []
    assert result["low_signal_pages"] == []
    assert result["orphaned_pages"] == ["PITFALLS.md"]
    assert any(finding["kind"] == "orphaned_page" for finding in result["findings"])

    orphaned_finding = next(
        finding for finding in result["findings"] if finding["kind"] == "orphaned_page"
    )
    assert orphaned_finding["kind"] == "orphaned_page"
    assert orphaned_finding["severity"] == "info"
    assert orphaned_finding["page"] == "PITFALLS.md"
    assert orphaned_finding["path"] == "PITFALLS.md"
    assert orphaned_finding["message"]
    assert orphaned_finding["suggestion"]


def test_lint_project_wiki_returns_ok_for_clean_wiki(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    source_dir = repo_root / "src" / "monitor" / "lib"
    source_dir.mkdir(parents=True)
    (source_dir / "system_prompt.py").write_text("PROMPT = 'ok'\n", encoding="utf-8")
    (wiki_dir / "INDEX.md").write_text(
        "See ARCHITECTURE.md and CONVENTIONS.md and src/monitor/lib/system_prompt.py\n",
        encoding="utf-8",
    )
    (wiki_dir / "ARCHITECTURE.md").write_text("architecture\n", encoding="utf-8")
    (wiki_dir / "CONVENTIONS.md").write_text("conventions\n", encoding="utf-8")

    result = lint_project_wiki(wiki_dir)

    assert result["ok"] is True
    assert result["missing_index"] is False
    assert result["broken_references"] == []
    assert result["missing_repo_paths"] == []
    assert result["oversized_pages"] == []
    assert result["low_signal_pages"] == []
    assert result["orphaned_pages"] == []
    assert result["findings"] == []


def test_format_wiki_lint_report_for_clean_wiki_shows_pass_and_no_findings(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    source_dir = repo_root / "src" / "monitor" / "lib"
    source_dir.mkdir(parents=True)
    (source_dir / "system_prompt.py").write_text("PROMPT = 'ok'\n", encoding="utf-8")
    (wiki_dir / "INDEX.md").write_text(
        "See ARCHITECTURE.md and src/monitor/lib/system_prompt.py\n",
        encoding="utf-8",
    )
    (wiki_dir / "ARCHITECTURE.md").write_text("architecture\n", encoding="utf-8")

    result = lint_project_wiki(wiki_dir)
    report = format_wiki_lint_report(result)

    assert "PASS" in report
    assert str(Path(wiki_dir)) in report
    assert "No findings" in report


def test_format_wiki_lint_report_for_mixed_findings_shows_fail_counts_and_sections(
    tmp_path,
):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    (repo_root / "src").mkdir()
    (repo_root / "src" / "existing.py").write_text("print('ok')\n", encoding="utf-8")
    (wiki_dir / "INDEX.md").write_text(
        "See ARCHITECTURE.md and src/existing.py and src/missing.py\n",
        encoding="utf-8",
    )
    (wiki_dir / "ARCHITECTURE.md").write_text(
        ("Plain paragraph with no structure.\n" * 85), encoding="utf-8"
    )

    result = lint_project_wiki(wiki_dir)
    report = format_wiki_lint_report(result)

    assert result["ok"] is False
    assert any(finding["severity"] == "warning" for finding in result["findings"])
    assert any(finding["severity"] == "info" for finding in result["findings"])
    assert "FAIL" in report
    assert "warning" in report.lower()
    assert "info" in report.lower()
    assert "src/missing.py" in report
    assert "ARCHITECTURE.md" in report
    assert "suggest" in report.lower()

    warning_index = report.lower().index("warning")
    info_index = report.lower().index("info")
    assert warning_index < info_index

    warning_count = sum(
        1 for finding in result["findings"] if finding["severity"] == "warning"
    )
    info_count = sum(1 for finding in result["findings"] if finding["severity"] == "info")
    assert str(warning_count) in report
    assert str(info_count) in report


def test_run_project_wiki_lint_for_clean_wiki_returns_ok_and_pass_report(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    source_dir = repo_root / "src" / "monitor" / "lib"
    source_dir.mkdir(parents=True)
    (source_dir / "system_prompt.py").write_text("PROMPT = 'ok'\n", encoding="utf-8")
    (wiki_dir / "INDEX.md").write_text(
        "See ARCHITECTURE.md and src/monitor/lib/system_prompt.py\n",
        encoding="utf-8",
    )
    (wiki_dir / "ARCHITECTURE.md").write_text("architecture\n", encoding="utf-8")

    result = run_project_wiki_lint(wiki_dir)

    assert result["ok"] is True
    assert result["missing_index"] is False
    assert result["broken_references"] == []
    assert result["missing_repo_paths"] == []
    assert result["oversized_pages"] == []
    assert result["low_signal_pages"] == []
    assert result["orphaned_pages"] == []
    assert result["findings"] == []
    assert "report" in result
    assert "PASS" in result["report"]


def test_run_project_wiki_lint_for_failing_wiki_returns_findings_and_fail_report(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    (repo_root / "src").mkdir()
    (repo_root / "src" / "existing.py").write_text("print('ok')\n", encoding="utf-8")
    (wiki_dir / "INDEX.md").write_text(
        "See ARCHITECTURE.md and src/existing.py and src/missing.py\n",
        encoding="utf-8",
    )
    (wiki_dir / "ARCHITECTURE.md").write_text(
        ("Plain paragraph with no structure.\n" * 85), encoding="utf-8"
    )

    result = run_project_wiki_lint(wiki_dir)

    assert result["ok"] is False
    assert "missing_index" in result
    assert "broken_references" in result
    assert "missing_repo_paths" in result
    assert "oversized_pages" in result
    assert "low_signal_pages" in result
    assert "orphaned_pages" in result
    assert "findings" in result
    assert "report" in result
    assert result["missing_index"] is False
    assert result["broken_references"] == []
    assert result["missing_repo_paths"] == ["src/missing.py"]
    assert result["oversized_pages"] == []
    assert result["low_signal_pages"] == ["ARCHITECTURE.md"]
    assert "FAIL" in result["report"]
    assert "src/missing.py" in result["report"]
    assert "ARCHITECTURE.md" in result["report"]


def test_run_project_wiki_structural_lint_returns_mode_tagged_result(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    source_dir = repo_root / "src" / "monitor" / "lib"
    source_dir.mkdir(parents=True)
    (source_dir / "system_prompt.py").write_text("PROMPT = 'ok'\n", encoding="utf-8")
    (wiki_dir / "INDEX.md").write_text(
        "See ARCHITECTURE.md and src/monitor/lib/system_prompt.py\n",
        encoding="utf-8",
    )
    (wiki_dir / "ARCHITECTURE.md").write_text("architecture\n", encoding="utf-8")

    from monitor.lib.monitor_wiki_linter import run_project_wiki_structural_lint

    result = run_project_wiki_structural_lint(wiki_dir)

    assert result["mode"] == "structural"
    assert result["ok"] is True
    assert "PASS" in result["report"]


def test_run_project_wiki_semantic_lint_reports_stale_location_claims(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (wiki_dir / "ARCHITECTURE.md").write_text(
        "The authoritative implementation lives in src/monitor/lib/missing_server.py\n",
        encoding="utf-8",
    )

    from monitor.lib.monitor_wiki_linter import run_project_wiki_semantic_lint

    result = run_project_wiki_semantic_lint(wiki_dir)

    assert result["mode"] == "semantic"
    assert result["ok"] is False
    assert result["findings"][0]["kind"] == "semantic_stale_location_claim"
    assert result["findings"][0]["path"] == "src/monitor/lib/missing_server.py"
    assert "authoritative implementation lives in" in result["findings"][0]["claim"].lower()
    assert "FAIL" in result["report"]


def test_run_project_wiki_semantic_lint_reports_stale_authority_claims(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (wiki_dir / "ARCHITECTURE.md").write_text(
        "The canonical guide is docs/process/current.md\n",
        encoding="utf-8",
    )

    from monitor.lib.monitor_wiki_linter import run_project_wiki_semantic_lint

    result = run_project_wiki_semantic_lint(wiki_dir)

    assert result["mode"] == "semantic"
    assert result["ok"] is False
    assert result["findings"][0]["kind"] == "semantic_stale_authority_claim"
    assert result["findings"][0]["path"] == "docs/process/current.md"
    assert "canonical guide" in result["findings"][0]["claim"].lower()
    assert "FAIL" in result["report"]



def test_run_project_wiki_semantic_lint_reports_stale_workflow_claims(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (wiki_dir / "ARCHITECTURE.md").write_text(
        "Build steps are in docs/build/current.md\n",
        encoding="utf-8",
    )

    from monitor.lib.monitor_wiki_linter import run_project_wiki_semantic_lint

    result = run_project_wiki_semantic_lint(wiki_dir)

    assert result["mode"] == "semantic"
    assert result["ok"] is False
    assert result["findings"][0]["kind"] == "semantic_stale_workflow_claim"
    assert result["findings"][0]["path"] == "docs/build/current.md"
    assert "build steps are in" in result["findings"][0]["claim"].lower()
    assert "FAIL" in result["report"]


def test_run_project_wiki_semantic_lint_reports_stale_ownership_claims(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (wiki_dir / "ARCHITECTURE.md").write_text(
        "Changes belong in src/monitor/lib/ownership_router.py\n",
        encoding="utf-8",
    )

    from monitor.lib.monitor_wiki_linter import run_project_wiki_semantic_lint

    result = run_project_wiki_semantic_lint(wiki_dir)

    assert result["mode"] == "semantic"
    assert result["ok"] is False
    assert result["findings"][0]["kind"] == "semantic_stale_ownership_claim"
    assert result["findings"][0]["path"] == "src/monitor/lib/ownership_router.py"
    assert "changes belong in" in result["findings"][0]["claim"].lower()
    assert "FAIL" in result["report"]


def test_run_project_wiki_semantic_lint_returns_pass_when_location_claim_path_exists(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    source_dir = repo_root / "src" / "monitor" / "lib"
    source_dir.mkdir(parents=True)
    (source_dir / "server.py").write_text("def create_server():\n    return None\n", encoding="utf-8")
    (wiki_dir / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (wiki_dir / "ARCHITECTURE.md").write_text(
        "The authoritative implementation lives in src/monitor/lib/server.py\n",
        encoding="utf-8",
    )

    from monitor.lib.monitor_wiki_linter import run_project_wiki_semantic_lint

    result = run_project_wiki_semantic_lint(wiki_dir)

    assert result["mode"] == "semantic"
    assert result["ok"] is True
    assert result["findings"] == []
    assert "No semantic findings" in result["report"]


def test_run_project_wiki_semantic_lint_returns_pass_when_ownership_claim_path_exists(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    source_dir = repo_root / "src" / "monitor" / "lib"
    source_dir.mkdir(parents=True)
    (source_dir / "ownership_router.py").write_text("OWNER = 'monitor'\n", encoding="utf-8")
    (wiki_dir / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (wiki_dir / "ARCHITECTURE.md").write_text(
        "Changes belong in src/monitor/lib/ownership_router.py\n",
        encoding="utf-8",
    )

    from monitor.lib.monitor_wiki_linter import run_project_wiki_semantic_lint

    result = run_project_wiki_semantic_lint(wiki_dir)

    assert result["mode"] == "semantic"
    assert result["ok"] is True
    assert result["findings"] == []
    assert "No semantic findings" in result["report"]


def test_run_project_wiki_semantic_lint_ignores_non_claim_lines_with_repo_paths(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (wiki_dir / "ARCHITECTURE.md").write_text(
        "Reference: src/monitor/lib/ownership_router.py\n",
        encoding="utf-8",
    )

    from monitor.lib.monitor_wiki_linter import run_project_wiki_semantic_lint

    result = run_project_wiki_semantic_lint(wiki_dir)

    assert result["mode"] == "semantic"
    assert result["ok"] is True
    assert result["findings"] == []
    assert "No semantic findings" in result["report"]


def test_run_project_wiki_semantic_lint_reports_alternate_ownership_phrase(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (wiki_dir / "ARCHITECTURE.md").write_text(
        "This area is owned by src/monitor/lib/owners.py\n",
        encoding="utf-8",
    )

    from monitor.lib.monitor_wiki_linter import run_project_wiki_semantic_lint

    result = run_project_wiki_semantic_lint(wiki_dir)

    assert result["mode"] == "semantic"
    assert result["ok"] is False
    assert result["findings"][0]["kind"] == "semantic_stale_ownership_claim"
    assert result["findings"][0]["path"] == "src/monitor/lib/owners.py"
    assert "owned by" in result["findings"][0]["claim"].lower()


def test_store_latest_wiki_lint_result_attaches_finding_ids_and_returns_result():
    result = {
        "mode": "semantic",
        "findings": [
            {
                "kind": "semantic_stale_location_claim",
                "page": "ARCHITECTURE.md",
                "path": "src/monitor/lib/missing_server.py",
                "claim": "The authoritative implementation lives in src/monitor/lib/missing_server.py",
                "message": "Wiki location claim references missing path: src/monitor/lib/missing_server.py",
                "suggestion": "Update the wiki claim.",
            }
        ],
    }

    stored = store_latest_wiki_lint_result(result)

    assert stored["findings"][0]["id"]
    assert stored["findings"][0]["id"] == latest_wiki_lint_result()["findings"][0]["id"]


def test_run_project_wiki_lint_mode_stores_latest_result_with_finding_ids(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (wiki_dir / "ARCHITECTURE.md").write_text(
        "The authoritative implementation lives in src/monitor/lib/missing_server.py\n",
        encoding="utf-8",
    )

    from monitor.lib.monitor_wiki_linter import run_project_wiki_lint_mode

    result = run_project_wiki_lint_mode(wiki_dir, "semantic")
    latest_result = latest_wiki_lint_result()

    assert latest_result is not None
    assert latest_result["mode"] == "semantic"
    assert latest_result["findings"][0]["id"] == result["findings"][0]["id"]
    assert "semantic_stale_location_claim" in result["report"]


def test_run_project_wiki_lint_mode_all_combines_structural_and_semantic_results(tmp_path):
    repo_root = tmp_path / "repo"
    wiki_dir = repo_root / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    source_dir = repo_root / "src" / "monitor" / "lib"
    source_dir.mkdir(parents=True)
    (source_dir / "system_prompt.py").write_text("PROMPT = 'ok'\n", encoding="utf-8")
    (wiki_dir / "INDEX.md").write_text(
        "See ARCHITECTURE.md and src/monitor/lib/system_prompt.py\n",
        encoding="utf-8",
    )
    (wiki_dir / "ARCHITECTURE.md").write_text("architecture\n", encoding="utf-8")

    from monitor.lib.monitor_wiki_linter import run_project_wiki_lint_mode

    result = run_project_wiki_lint_mode(wiki_dir, "all")

    assert result["mode"] == "all"
    assert result["ok"] is True
    assert result["structural"]["mode"] == "structural"
    assert result["semantic"]["mode"] == "semantic"
    assert "== Structural ==" in result["report"]
    assert "== Semantic ==" in result["report"]


def test_run_project_wiki_lint_mode_rejects_unsupported_mode(tmp_path):
    from monitor.lib.monitor_wiki_linter import run_project_wiki_lint_mode

    with pytest.raises(ValueError, match="Unsupported wiki lint mode"):
        run_project_wiki_lint_mode(tmp_path, "unknown")


def _appdir_style_layout(tmp_path):
    """Build a production-style layout where the wiki lives apart from the repo.

    Mirrors the real appdir layout: the wiki is at
    ``appdir/monitor/monitor-wiki/<slug>`` while the project source lives in a
    separate repository tree, so ``wiki_dir.parent.parent`` is NOT the repo root.
    """
    repo_root = tmp_path / "realrepo"
    source_dir = repo_root / "src" / "monitor" / "lib"
    source_dir.mkdir(parents=True)
    (source_dir / "app.py").write_text("print('exists')\n", encoding="utf-8")

    wiki_dir = tmp_path / "appdir" / "monitor" / "monitor-wiki" / "slug"
    wiki_dir.mkdir(parents=True)
    return repo_root, wiki_dir


def test_lint_project_wiki_resolves_repo_paths_against_explicit_repo_root(tmp_path):
    repo_root, wiki_dir = _appdir_style_layout(tmp_path)
    (wiki_dir / "INDEX.md").write_text(
        "See src/monitor/lib/app.py and src/monitor/lib/gone.py\n",
        encoding="utf-8",
    )

    result = lint_project_wiki(wiki_dir, repo_root)

    # The real file resolves against the passed repo root and is NOT flagged;
    # only the genuinely-missing path is reported.
    assert result["missing_repo_paths"] == ["src/monitor/lib/gone.py"]


def test_lint_project_wiki_without_repo_root_misresolves_appdir_layout(tmp_path):
    repo_root, wiki_dir = _appdir_style_layout(tmp_path)
    (wiki_dir / "INDEX.md").write_text(
        "See src/monitor/lib/app.py\n",
        encoding="utf-8",
    )

    # Without an explicit repo root the fallback uses wiki_dir.parent.parent,
    # which is not the repo in the appdir layout, so the real path is missed.
    result = lint_project_wiki(wiki_dir)

    assert result["missing_repo_paths"] == ["src/monitor/lib/app.py"]


def test_run_project_wiki_semantic_lint_honors_explicit_repo_root(tmp_path):
    repo_root, wiki_dir = _appdir_style_layout(tmp_path)
    (wiki_dir / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (wiki_dir / "ARCHITECTURE.md").write_text(
        "The CLI entry point is implemented in src/monitor/lib/app.py\n"
        "Routing is owned by src/monitor/lib/gone.py\n",
        encoding="utf-8",
    )

    from monitor.lib.monitor_wiki_linter import run_project_wiki_semantic_lint

    result = run_project_wiki_semantic_lint(wiki_dir, repo_root)

    assert result["ok"] is False
    paths = {finding["path"] for finding in result["findings"]}
    assert paths == {"src/monitor/lib/gone.py"}


def test_run_project_wiki_lint_mode_threads_repo_root(tmp_path):
    repo_root, wiki_dir = _appdir_style_layout(tmp_path)
    (wiki_dir / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (wiki_dir / "ARCHITECTURE.md").write_text(
        "The authoritative implementation lives in src/monitor/lib/app.py\n",
        encoding="utf-8",
    )

    from monitor.lib.monitor_wiki_linter import run_project_wiki_lint_mode

    result = run_project_wiki_lint_mode(wiki_dir, "semantic", repo_root)

    # The claim points at a real file under the explicit repo root, so the
    # semantic pass is clean.
    assert result["ok"] is True
    assert result["findings"] == []
