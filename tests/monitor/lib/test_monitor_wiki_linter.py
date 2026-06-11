"""Tests for the structural monitor wiki linter."""

from pathlib import Path

from monitor.lib.monitor_wiki_linter import lint_project_wiki, markdown_pages_in_project_wiki, referenced_wiki_pages


def test_referenced_wiki_pages_returns_unique_non_index_entries(tmp_path):
    index_path = tmp_path / "INDEX.md"
    index_path.write_text(
        "See ARCHITECTURE.md and CONVENTIONS.md and ARCHITECTURE.md and INDEX.md\n",
        encoding="utf-8",
    )

    assert referenced_wiki_pages(index_path) == ["ARCHITECTURE.md", "CONVENTIONS.md"]


def test_markdown_pages_in_project_wiki_lists_direct_markdown_files(tmp_path):
    (tmp_path / "INDEX.md").write_text("index\n", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text("architecture\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not markdown\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "NESTED.md").write_text("nested\n", encoding="utf-8")

    assert markdown_pages_in_project_wiki(tmp_path) == ["ARCHITECTURE.md", "INDEX.md"]


def test_lint_project_wiki_reports_missing_index(tmp_path):
    (tmp_path / "ARCHITECTURE.md").write_text("architecture\n", encoding="utf-8")

    result = lint_project_wiki(tmp_path)

    assert result["ok"] is False
    assert result["missing_index"] is True
    assert result["broken_references"] == []
    assert result["orphaned_pages"] == ["ARCHITECTURE.md"]
    assert any(finding["kind"] == "missing_index" for finding in result["findings"])


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
    assert any(finding["kind"] == "broken_reference" for finding in result["findings"])


def test_lint_project_wiki_reports_orphaned_pages(tmp_path):
    (tmp_path / "INDEX.md").write_text("See ARCHITECTURE.md\n", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text("architecture\n", encoding="utf-8")
    (tmp_path / "PITFALLS.md").write_text("pitfalls\n", encoding="utf-8")

    result = lint_project_wiki(tmp_path)

    assert result["ok"] is False
    assert result["orphaned_pages"] == ["PITFALLS.md"]
    assert any(finding["kind"] == "orphaned_page" for finding in result["findings"])


def test_lint_project_wiki_returns_ok_for_clean_wiki(tmp_path):
    (tmp_path / "INDEX.md").write_text(
        "See ARCHITECTURE.md and CONVENTIONS.md\n",
        encoding="utf-8",
    )
    (tmp_path / "ARCHITECTURE.md").write_text("architecture\n", encoding="utf-8")
    (tmp_path / "CONVENTIONS.md").write_text("conventions\n", encoding="utf-8")

    result = lint_project_wiki(tmp_path)

    assert result["ok"] is True
    assert result["missing_index"] is False
    assert result["broken_references"] == []
    assert result["orphaned_pages"] == []
    assert result["findings"] == []
