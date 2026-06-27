"""Tests for the chroma-db CLI entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from monitor.lib import chroma_cli


def test_build_parser_includes_expected_commands() -> None:
    """The parser should expose the chroma-db subcommands."""
    parser = chroma_cli.build_parser()
    help_text = parser.format_help()

    assert "list-collections" in help_text
    assert "inspect-collection" in help_text
    assert "dump-collection" in help_text
    assert "query" in help_text
    assert "get-by-id" in help_text
    assert "delete-by-id" in help_text
    assert "replace-by-id" in help_text


def test_resolve_collection_name_prefers_name() -> None:
    """A command-local --name should take precedence over the global default."""
    args = argparse.Namespace(name="local", collection="global")

    assert chroma_cli.resolve_collection_name(args) == "local"


def test_resolve_collection_name_uses_global_collection() -> None:
    """The global --collection should be used when --name is absent."""
    args = argparse.Namespace(name=None, collection="global")

    assert chroma_cli.resolve_collection_name(args) == "global"


def test_resolve_collection_name_requires_name_when_missing() -> None:
    """A collection name should be required for collection-specific commands."""
    args = argparse.Namespace(name=None, collection=None)

    with pytest.raises(SystemExit, match="A collection name is required"):
        chroma_cli.resolve_collection_name(args)


def test_confirm_destructive_action_aborts_when_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The confirmation helper should abort when the user rejects the prompt."""
    monkeypatch.setattr("builtins.input", lambda prompt: "no")

    with pytest.raises(SystemExit, match="Aborted"):
        chroma_cli.confirm_destructive_action("Delete?", False)


def test_confirm_destructive_action_skips_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """The confirmation helper should not prompt when skipped."""
    called = {"value": False}

    def fail_input(prompt: str) -> str:
        called["value"] = True
        raise AssertionError("input should not be called")

    monkeypatch.setattr("builtins.input", fail_input)
    chroma_cli.confirm_destructive_action("Delete?", True)

    assert called["value"] is False


def test_load_documents_from_files_reads_content(tmp_path: Path) -> None:
    """Replacement documents should be loaded from text files."""
    file_one = tmp_path / "one.txt"
    file_two = tmp_path / "two.txt"
    file_one.write_text("one", encoding="utf-8")
    file_two.write_text("two", encoding="utf-8")

    documents = chroma_cli.load_documents_from_files([str(file_one), str(file_two)])

    assert documents == ["one", "two"]


def test_main_prints_json_for_structured_commands(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI should print JSON for structured command results."""
    monkeypatch.setattr(chroma_cli, "run_command", lambda args: {"hello": "world"})

    exit_code = chroma_cli.main(["list-collections"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"hello": "world"' in captured.out
