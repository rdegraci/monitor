"""Tests for the surgical text-file editor tools.

Covers:
- directory view (regression for the old file_exists-only gate that made
  directory paths unreachable)
- text_file_create dict return shape + parent-directory auto-creation
- text_file_str_replace_in_file uniqueness requirement (errors on 0 or >1 matches)
- text_file_insert_text_at_line semantic (inserts BEFORE the given line) and
  dict return shape
"""

import os

from monitor.lib import text_file_editor


# --- text_file_or_directory_view --------------------------------------------


def test_view_file_returns_contents(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("alpha\nbeta\n")
    out = text_file_editor.text_file_or_directory_view("view", str(path))
    assert isinstance(out, str)
    assert "alpha" in out and "beta" in out


def test_view_directory_returns_listing(tmp_path):
    """Regression: the old code used file_exists() as a precondition, which
    returns False for directories — making directory view permanently broken."""
    (tmp_path / "child.txt").write_text("x")
    (tmp_path / "sub").mkdir()

    out = text_file_editor.text_file_or_directory_view("view", str(tmp_path))

    assert isinstance(out, str)
    assert "child.txt" in out
    assert "sub" in out
    assert "Path not found" not in out


def test_view_missing_path_errors_cleanly(tmp_path):
    out = text_file_editor.text_file_or_directory_view("view", str(tmp_path / "missing"))
    assert out.startswith("Path not found")


def test_view_range_subset(tmp_path):
    path = tmp_path / "f.txt"
    path.write_text("one\ntwo\nthree\nfour\n")
    out = text_file_editor.text_file_or_directory_view("view", str(path), view_range=[2, 3])
    assert "two" in out and "three" in out
    assert "one" not in out and "four" not in out


# --- text_file_create -------------------------------------------------------


def test_create_returns_dict_with_lines_created(tmp_path):
    path = tmp_path / "new.py"
    result = text_file_editor.text_file_create("create", str(path), "line1\nline2\n")
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert result["path"] == str(path)
    assert result["lines_created"] == 2
    assert path.read_text() == "line1\nline2\n"


def test_create_auto_creates_parent_directories(tmp_path):
    nested = tmp_path / "a" / "b" / "c" / "new.py"
    result = text_file_editor.text_file_create("create", str(nested), "x\n")
    assert result["ok"] is True
    assert nested.exists()
    assert (tmp_path / "a" / "b" / "c").is_dir()


def test_create_fails_when_file_exists(tmp_path):
    path = tmp_path / "x.py"
    path.write_text("existing")
    result = text_file_editor.text_file_create("create", str(path), "new")
    assert result["ok"] is False
    assert "already exists" in result["error"]
    assert path.read_text() == "existing"  # unchanged


# --- text_file_str_replace_in_file ------------------------------------------


def test_str_replace_unique_match_succeeds(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("foo = 1\nbar = 2\n")
    result = text_file_editor.text_file_str_replace_in_file(
        "str_replace", str(path), "foo = 1", "foo = 99"
    )
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert result["path"] == str(path)
    assert "diff" in result and "+foo = 99" in result["diff"]
    assert path.read_text() == "foo = 99\nbar = 2\n"


def test_str_replace_zero_matches_errors(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("foo\n")
    result = text_file_editor.text_file_str_replace_in_file(
        "str_replace", str(path), "nonexistent", "anything"
    )
    assert result["ok"] is False
    assert "not found" in result["error"].lower()
    assert path.read_text() == "foo\n"  # unchanged


def test_str_replace_multi_match_errors_without_modifying(tmp_path):
    """Regression for the silent multi-replace footgun: a non-unique old_str
    must fail loudly, not quietly rewrite every occurrence."""
    path = tmp_path / "m.py"
    path.write_text("return None\nx = 1\nreturn None\n")
    result = text_file_editor.text_file_str_replace_in_file(
        "str_replace", str(path), "return None", "return 0"
    )
    assert result["ok"] is False
    assert "matches 2 times" in result["error"]
    assert "unique" in result["error"]
    # File unchanged — no partial / wholesale rewrite.
    assert path.read_text() == "return None\nx = 1\nreturn None\n"


def test_str_replace_does_not_leave_tmp_files(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("hello\n")
    text_file_editor.text_file_str_replace_in_file("str_replace", str(path), "hello", "world")
    # No .tmp companion left behind from the old pattern.
    assert not (tmp_path / "m.py.tmp").exists()


# --- text_file_insert_text_at_line ------------------------------------------


def test_insert_inserts_before_given_line(tmp_path):
    """insert_line=2 should insert AT position 1 (before existing line 2)."""
    path = tmp_path / "m.py"
    path.write_text("line1\nline2\nline3\n")
    result = text_file_editor.text_file_insert_text_at_line(
        "insert", str(path), 2, "inserted\n"
    )
    assert result["ok"] is True
    assert result["inserted_at_line"] == 2
    assert path.read_text() == "line1\ninserted\nline2\nline3\n"


def test_insert_at_line_one_puts_text_at_top(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("line1\nline2\n")
    text_file_editor.text_file_insert_text_at_line("insert", str(path), 1, "top\n")
    assert path.read_text() == "top\nline1\nline2\n"


def test_insert_at_total_plus_one_appends(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("line1\nline2\n")
    text_file_editor.text_file_insert_text_at_line("insert", str(path), 3, "appended\n")
    assert path.read_text() == "line1\nline2\nappended\n"


def test_insert_auto_appends_trailing_newline(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("a\nb\n")
    text_file_editor.text_file_insert_text_at_line("insert", str(path), 2, "no-newline")
    assert "no-newline\n" in path.read_text()


def test_insert_out_of_range_errors(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("line1\nline2\n")
    result = text_file_editor.text_file_insert_text_at_line("insert", str(path), 99, "x\n")
    assert result["ok"] is False
    assert "exceeds file length" in result["error"]
    assert path.read_text() == "line1\nline2\n"  # unchanged


def test_insert_returns_dict_with_diff(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("a\nb\n")
    result = text_file_editor.text_file_insert_text_at_line("insert", str(path), 2, "c\n")
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert "+c" in result["diff"]
    assert result["lines_changed"] == 1


# --- str_replace_based_edit_tool dispatcher (Anthropic-native path) ---------


def test_dispatcher_str_replace_success_returns_success_envelope(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("hello\nworld\n")
    result = text_file_editor.str_replace_based_edit_tool(
        "str_replace", str(path), old_str="hello", new_str="hi"
    )
    assert result["success"] is True
    assert "Replaced" in result["message"]
    assert path.read_text() == "hi\nworld\n"


def test_dispatcher_str_replace_failure_surfaces_dict_error(tmp_path):
    """Regression: underlying tools now return dicts; the dispatcher must
    inspect ``ok``, not just match string heuristics, otherwise a failing
    surgical edit would be reported back as success."""
    path = tmp_path / "m.py"
    path.write_text("foo\nfoo\n")  # multi-match → ok=False
    result = text_file_editor.str_replace_based_edit_tool(
        "str_replace", str(path), old_str="foo", new_str="bar"
    )
    assert result["success"] is False
    assert "matches 2 times" in result["error"]
    assert path.read_text() == "foo\nfoo\n"  # unchanged


def test_dispatcher_insert_failure_surfaces_dict_error(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("only\n")
    result = text_file_editor.str_replace_based_edit_tool(
        "insert", str(path), insert_line=99, new_str="x\n"
    )
    assert result["success"] is False
    assert "exceeds file length" in result["error"]


def test_dispatcher_create_failure_surfaces_dict_error(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("existing")
    result = text_file_editor.str_replace_based_edit_tool(
        "create", str(path), file_text="new"
    )
    assert result["success"] is False
    assert "already exists" in result["error"]


def test_dispatcher_view_returns_content_in_message(tmp_path):
    """view still returns a string from the underlying tool; the dispatcher
    should pass that through as the success message (file content)."""
    path = tmp_path / "m.py"
    path.write_text("alpha\nbeta\n")
    result = text_file_editor.str_replace_based_edit_tool("view", str(path))
    assert result["success"] is True
    assert "alpha" in result["message"]


def test_dispatcher_view_missing_path_surfaces_error(tmp_path):
    result = text_file_editor.str_replace_based_edit_tool("view", str(tmp_path / "no.py"))
    assert result["success"] is False
    assert "Path not found" in result["error"]


def test_dispatcher_registered_in_available_tools_under_both_names():
    """Anthropic models emit either ``str_replace_based_edit_tool`` (newer) or
    ``str_replace_editor`` (Sonnet 3.7); both must dispatch to the same
    handler so the harness can find the tool when the model invokes it."""
    from monitor.lib.tool_definitions import AVAILABLE_TOOLS

    assert "str_replace_based_edit_tool" in AVAILABLE_TOOLS
    assert "str_replace_editor" in AVAILABLE_TOOLS
    assert AVAILABLE_TOOLS["str_replace_based_edit_tool"] is AVAILABLE_TOOLS["str_replace_editor"]
