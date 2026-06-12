"""Tests for the structural monitor wiki linter."""

from pathlib import Path

from monitor.lib.monitor_wiki_linter import (
    format_wiki_lint_report,
    lint_project_wiki,
    low_signal_wiki_pages,
    markdown_pages_in_project_wiki,
    oversized_wiki_pages,
    referenced_repo_paths,
    referenced_wiki_pages,
    run_project_wiki_lint,
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
