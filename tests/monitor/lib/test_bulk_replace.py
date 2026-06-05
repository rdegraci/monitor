"""Tests for the deterministic bulk-replace tool and its verification gate.

Covers the design guarantees from
docs/cache/PLAN_DETERMINISTIC_BULK_REPLACE_TOOL.md:
- literal replace-all (single + multi file via glob) with accurate counts
- dry-run default (previews, writes nothing)
- word-boundary safety ('count' must not touch 'account')
- regex opt-in + clean failure on bad regex
- expected_count latch
- three-tier verification gate (code / structured / freeform) + batch atomicity
- binary / out-of-tree skipping
"""

import os

import pytest

from monitor.lib import bulk_replace
from monitor.lib.bulk_replace import bulk_replace_in_files
from monitor.lib import edit_verification


@pytest.fixture(autouse=True)
def _in_repo(tmp_path, monkeypatch):
    """Run each test inside a fake repo root (so the repo-tree guard allows the
    tmp files) and from that cwd."""
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- literal replace-all ----------------------------------------------------


def test_literal_replace_all_single_file_counts(_in_repo):
    p = _in_repo / "a.txt"
    p.write_text("foo bar foo baz foo\n")
    result = bulk_replace_in_files("foo", "qux", str(p), dry_run=False)
    assert result["ok"] is True
    assert result["occurrences"] == 3
    assert result["files_changed"] == 1
    assert p.read_text() == "qux bar qux baz qux\n"


def test_multi_file_via_glob(_in_repo):
    (_in_repo / "one.txt").write_text("alpha alpha\n")
    (_in_repo / "two.txt").write_text("alpha\n")
    (_in_repo / "skip.md").write_text("alpha\n")
    result = bulk_replace_in_files("alpha", "beta", "*.txt", dry_run=False)
    assert result["ok"] is True
    assert result["occurrences"] == 3
    assert result["files_changed"] == 2
    assert (_in_repo / "one.txt").read_text() == "beta beta\n"
    assert (_in_repo / "two.txt").read_text() == "beta\n"
    # .md not in the *.txt glob → untouched
    assert (_in_repo / "skip.md").read_text() == "alpha\n"


def test_no_match_is_ok_no_change(_in_repo):
    p = _in_repo / "a.txt"
    p.write_text("hello\n")
    result = bulk_replace_in_files("absent", "x", str(p), dry_run=False)
    assert result["ok"] is True
    assert result["occurrences"] == 0
    assert result["files_changed"] == 0
    assert p.read_text() == "hello\n"


# --- dry run default --------------------------------------------------------


def test_dry_run_is_default_and_writes_nothing(_in_repo):
    p = _in_repo / "a.txt"
    p.write_text("foo foo\n")
    result = bulk_replace_in_files("foo", "bar", str(p))  # no dry_run arg
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["occurrences"] == 2
    assert result["per_file"][0]["diff"]  # a diff was produced
    assert p.read_text() == "foo foo\n"  # unchanged on disk


# --- word boundary ----------------------------------------------------------


def test_word_boundary_does_not_match_substring(_in_repo):
    p = _in_repo / "a.txt"
    p.write_text("count the account counter\n")
    result = bulk_replace_in_files(
        "count", "total", str(p), word_boundary=True, dry_run=False
    )
    assert result["ok"] is True
    assert result["occurrences"] == 1  # only the standalone 'count'
    assert p.read_text() == "total the account counter\n"


def test_literal_without_word_boundary_matches_substring(_in_repo):
    p = _in_repo / "a.txt"
    p.write_text("count account\n")
    result = bulk_replace_in_files("count", "total", str(p), dry_run=False)
    assert result["occurrences"] == 2  # 'count' and the one inside 'account'
    assert p.read_text() == "total actotal\n"


# --- regex opt-in -----------------------------------------------------------


def test_regex_opt_in(_in_repo):
    p = _in_repo / "a.txt"
    p.write_text("a1 b2 c3\n")
    result = bulk_replace_in_files(
        r"[a-z]\d", "X", str(p), literal=False, dry_run=False
    )
    assert result["ok"] is True
    assert result["occurrences"] == 3
    assert p.read_text() == "X X X\n"


def test_bad_regex_fails_cleanly_no_write(_in_repo):
    p = _in_repo / "a.txt"
    p.write_text("hello\n")
    result = bulk_replace_in_files("(unclosed", "x", str(p), literal=False, dry_run=False)
    assert result["ok"] is False
    assert "regex" in result["error"].lower()
    assert p.read_text() == "hello\n"


def test_replacement_text_is_literal_in_regex_mode(_in_repo):
    p = _in_repo / "a.txt"
    p.write_text("ab\n")
    # '\1' must be written literally, not interpreted as a backreference.
    result = bulk_replace_in_files(r"a(b)", r"<\1>", str(p), literal=False, dry_run=False)
    assert result["ok"] is True
    assert p.read_text() == "<\\1>\n"


# --- expected_count latch ---------------------------------------------------


def test_expected_count_mismatch_aborts(_in_repo):
    p = _in_repo / "a.txt"
    p.write_text("x x x\n")
    result = bulk_replace_in_files("x", "y", str(p), expected_count=2, dry_run=False)
    assert result["ok"] is False
    assert result["occurrences"] == 3
    assert p.read_text() == "x x x\n"  # untouched


def test_expected_count_match_applies(_in_repo):
    p = _in_repo / "a.txt"
    p.write_text("x x x\n")
    result = bulk_replace_in_files("x", "y", str(p), expected_count=3, dry_run=False)
    assert result["ok"] is True
    assert p.read_text() == "y y y\n"


# --- verification gate ------------------------------------------------------


def test_verification_rejects_broken_python(_in_repo):
    p = _in_repo / "m.py"
    p.write_text("def f():\n    return 1\n")
    # Replacing the body with a dangling token breaks syntax.
    result = bulk_replace_in_files("return 1", "return (", str(p), dry_run=False)
    assert result["ok"] is False
    assert result["verification_failures"]
    assert p.read_text() == "def f():\n    return 1\n"  # unchanged


def test_verification_rejects_broken_json(_in_repo):
    p = _in_repo / "c.json"
    p.write_text('{"name": "alpha"}\n')
    # Replacing the quoted value's closing context with a brace breaks JSON.
    result = bulk_replace_in_files('"alpha"', '"alpha",,', str(p), dry_run=False)
    assert result["ok"] is False
    assert p.read_text() == '{"name": "alpha"}\n'


def test_freeform_text_writes_without_gate(_in_repo):
    p = _in_repo / "notes.md"
    p.write_text("# title (\n")  # invalid as code, fine as markdown
    result = bulk_replace_in_files("title", "heading", str(p), dry_run=False)
    assert result["ok"] is True
    assert p.read_text() == "# heading (\n"


def test_batch_atomicity_one_bad_file_aborts_all(_in_repo):
    good = _in_repo / "good.py"
    good.write_text("x = 1\n")
    bad = _in_repo / "bad.py"
    bad.write_text("y = 1\n")
    # Replace '= 1' everywhere; in bad.py turn it into a syntax error.
    # Use two separate, valid-vs-invalid replacements is hard in one pass, so
    # craft an edit that breaks one file: replace '1' with '(' across both.
    result = bulk_replace_in_files("1", "(", "*.py", dry_run=False)
    assert result["ok"] is False
    # Neither file written — all-or-nothing.
    assert good.read_text() == "x = 1\n"
    assert bad.read_text() == "y = 1\n"


# --- scope safety -----------------------------------------------------------


def test_binary_file_skipped(_in_repo):
    b = _in_repo / "blob.bin"
    b.write_bytes(b"foo\x00foo\n")
    result = bulk_replace_in_files("foo", "bar", str(b), dry_run=False)
    assert result["ok"] is False  # no editable files matched
    assert b.read_bytes() == b"foo\x00foo\n"


def test_no_match_glob_reports_skip(_in_repo):
    result = bulk_replace_in_files("a", "b", "*.nonexistent", dry_run=False)
    assert result["ok"] is False
    assert "No editable files" in result["error"]


# --- validation -------------------------------------------------------------


def test_empty_old_rejected(_in_repo):
    p = _in_repo / "a.txt"
    p.write_text("x\n")
    result = bulk_replace_in_files("", "y", str(p))
    assert result["ok"] is False


# --- verification gate unit (tiers) -----------------------------------------


def test_gate_python_ok_and_bad():
    ok, err, tier = edit_verification.verify_file_content("x.py", "a = 1\n")
    assert ok and tier == "code"
    ok, err, tier = edit_verification.verify_file_content("x.py", "def (:\n")
    assert not ok and tier == "code"


def test_gate_json_tier():
    ok, _, tier = edit_verification.verify_file_content("x.json", '{"a": 1}')
    assert ok and tier == "structured"
    ok, _, tier = edit_verification.verify_file_content("x.json", "{not json}")
    assert not ok and tier == "structured"


def test_gate_freeform_skips():
    ok, err, tier = edit_verification.verify_file_content("x.md", "# anything (\n")
    assert ok and err is None and tier == "freeform"
