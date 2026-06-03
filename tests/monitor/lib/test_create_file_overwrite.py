"""Tests for create_file's overwrite parameter.

Default behavior (overwrite=False) remains strict — refuses to clobber
existing files. The new overwrite=True branch explicitly replaces the
existing contents, for use by LLMs that have already inspected the file
and intend a full replacement.

Edge cases covered:
  - overwrite=False on a new path → creates the file (the regular path)
  - overwrite=False on an existing path → refuses with error JSON
  - overwrite=True on a new path → creates (overwrite is permission, not requirement)
  - overwrite=True on an existing path → replaces contents
  - Directory at the path → always rejected, regardless of overwrite
  - Response JSON shape includes overwritten flag so callers can confirm
"""

import json

import pytest

from monitor.lib.os import create_file


def test_create_file_default_refuses_to_overwrite(tmp_path):
    """Backwards-compat: callers that don't pass overwrite see the strict
    behavior. The error message hints at the new param so the LLM has a
    clear recovery path."""
    target = tmp_path / "README.md"
    target.write_text("existing content")

    result = json.loads(create_file(str(target), "new content"))

    assert "error" in result
    assert "already exists" in result["error"]
    assert "overwrite=True" in result["error"]  # recovery hint surfaced
    # The pre-existing content is untouched.
    assert target.read_text() == "existing content"


def test_create_file_explicit_no_overwrite_refuses(tmp_path):
    """Passing overwrite=False explicitly is equivalent to the default."""
    target = tmp_path / "README.md"
    target.write_text("v1")

    result = json.loads(create_file(str(target), "v2", overwrite=False))

    assert "error" in result
    assert target.read_text() == "v1"


def test_create_file_overwrite_replaces_existing_content(tmp_path):
    """overwrite=True actually replaces the file's contents. The success
    response includes overwritten=True so the caller can confirm."""
    target = tmp_path / "README.md"
    target.write_text("OLD VERSION")

    result = json.loads(create_file(str(target), "NEW VERSION", overwrite=True))

    assert "result" in result
    assert result["overwritten"] is True
    assert "Replaced" in result["result"]
    assert target.read_text() == "NEW VERSION"


def test_create_file_overwrite_on_new_path_creates(tmp_path):
    """overwrite=True is permission, not requirement — on a new path it
    still creates a new file. The overwritten flag is False in the
    response so the caller can tell it wasn't a replacement."""
    target = tmp_path / "fresh.md"
    assert not target.exists()

    result = json.loads(create_file(str(target), "fresh content", overwrite=True))

    assert "result" in result
    assert result["overwritten"] is False
    assert "Created" in result["result"]
    assert target.read_text() == "fresh content"


def test_create_file_default_creates_new_file(tmp_path):
    """The normal new-file path still works with the default overwrite=False."""
    target = tmp_path / "new.md"

    result = json.loads(create_file(str(target), "hello"))

    assert "result" in result
    assert result["overwritten"] is False
    assert target.read_text() == "hello"


def test_create_file_directory_collision_rejected_regardless_of_overwrite(tmp_path):
    """A directory at the path is never something we should write a file
    into — overwrite=True does NOT bypass this check. Distinct from the
    file-exists case: a directory can hold many user files we'd destroy."""
    target = tmp_path / "subdir"
    target.mkdir()

    # Both branches must refuse.
    result_false = json.loads(create_file(str(target), "x", overwrite=False))
    assert "error" in result_false
    assert "directory" in result_false["error"]

    result_true = json.loads(create_file(str(target), "x", overwrite=True))
    assert "error" in result_true
    assert "directory" in result_true["error"]

    # Directory still exists.
    assert target.is_dir()


def test_create_file_creates_parent_directories(tmp_path):
    """Parent-directory auto-creation is independent of overwrite. Sanity-
    check that we haven't broken it."""
    nested = tmp_path / "a" / "b" / "c" / "new.txt"

    result = json.loads(create_file(str(nested), "deep file"))

    assert "result" in result
    assert nested.read_text() == "deep file"
    assert (tmp_path / "a" / "b" / "c").is_dir()
