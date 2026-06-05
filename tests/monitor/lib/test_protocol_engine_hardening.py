"""Tests for the edit-engine hardening (PLAN_HARDEN_EDIT.md).

Covers, against the ProtocolEngine, without invoking the LLM:
- Part 1 verification gate: reject broken code/JSON unwritten; accept valid;
  freeform skips; .rejected sidecar written; success path writes.
- Part 2 collateral footprint computation.
- Part 3 syntax-aware chunk boundaries (snap to blank line; single-chunk
  unchanged; fallback when no safe seam).
- Part 4 agent-level reflection: public entrypoint converts
  EditVerificationError into an actionable message and leaves the file alone.
- Partial saves bypass the gate (failure sidecar).
"""

import os

import pytest
from unittest.mock import Mock

from monitor.lib import protocol_engine
from monitor.lib.protocol_engine import ProtocolEngine, EditVerificationError


def _engine(tmp_path, name="m.py"):
    eng = ProtocolEngine(model="test", system_prompt="sys", middleware=Mock())
    eng.source_file = str(tmp_path / name)
    return eng


# --- Part 1: verification gate ----------------------------------------------


def test_gate_rejects_broken_python_no_write(tmp_path):
    eng = _engine(tmp_path)
    eng._modification_script_content = "def f():\n    return 1\n"
    eng.chunks = ["def f(:\n    return 1\n"]  # broken syntax
    with pytest.raises(EditVerificationError) as ei:
        eng._assemble_and_save()
    assert ei.value.tier == "code"
    # Target file never created; rejected sidecar holds the bad content.
    assert not os.path.exists(eng.source_file)
    assert os.path.exists(eng.source_file + ".rejected")


def test_gate_rejects_broken_json_no_write(tmp_path):
    eng = _engine(tmp_path, "c.json")
    eng._modification_script_content = '{"a": 1}\n'
    eng.chunks = ['{"a": 1,,}\n']  # broken JSON
    with pytest.raises(EditVerificationError) as ei:
        eng._assemble_and_save()
    assert ei.value.tier == "structured"
    assert not os.path.exists(eng.source_file)


def test_gate_accepts_valid_python_and_writes(tmp_path):
    eng = _engine(tmp_path)
    eng._modification_script_content = "x = 1\n"
    eng.chunks = ["x = 2\n"]
    result = eng._assemble_and_save()
    assert "Task completed successfully" in result
    assert "changed +" in result  # footprint note included
    with open(eng.source_file) as f:
        assert f.read() == "x = 2\n"


def test_gate_skips_freeform_text(tmp_path):
    eng = _engine(tmp_path, "notes.md")
    eng._modification_script_content = "# title (\n"
    eng.chunks = ["# heading (\n"]  # invalid as code, fine as markdown
    result = eng._assemble_and_save()
    assert "Task completed successfully" in result
    with open(eng.source_file) as f:
        assert f.read() == "# heading (\n"


def test_rejected_sidecar_has_bad_content(tmp_path):
    eng = _engine(tmp_path)
    eng._modification_script_content = "x = 1\n"
    bad = "def (oops\n"
    eng.chunks = [bad]
    with pytest.raises(EditVerificationError):
        eng._assemble_and_save()
    with open(eng.source_file + ".rejected") as f:
        assert "def (oops" in f.read()


# --- Part 2: collateral footprint -------------------------------------------


def test_collateral_footprint_counts(tmp_path):
    eng = _engine(tmp_path)
    fp = eng._collateral_footprint("a\nb\nc\n", "a\nB\nc\nd\n")
    assert fp["added"] >= 1 and fp["removed"] >= 1
    assert fp["hunks"] >= 1
    assert fp["ratio"] > 0


# --- Part 3: syntax-aware chunk boundaries ----------------------------------


def test_single_chunk_for_small_file(tmp_path):
    eng = _engine(tmp_path)
    plan = eng._make_chunk_plan("a\nb\nc\n")
    assert plan["expected_chunks"] == 1
    assert plan["line_ranges"] == [(1, 3)]


def test_boundary_snaps_to_blank_line(tmp_path):
    eng = _engine(tmp_path)
    eng.lines_per_chunk = 5
    content = (
        "def a():\n"      # 1
        "    x = 1\n"      # 2
        "\n"               # 3  <- blank seam
        "def b():\n"      # 4
        "    y = (\n"      # 5  <- target_end, mid-construct (open paren)
        "        2)\n"     # 6
        "def c():\n"      # 7
        "    pass\n"       # 8
    )
    plan = eng._make_chunk_plan(content)
    # First boundary must snap back to the blank line (3), not split at 5.
    assert plan["line_ranges"][0] == (1, 3)
    # Ranges remain contiguous and cover the whole file.
    assert plan["line_ranges"][0][0] == 1
    assert plan["line_ranges"][-1][1] == 8


def test_boundary_falls_back_when_no_safe_seam(tmp_path):
    eng = _engine(tmp_path)
    eng.lines_per_chunk = 3
    # All lines indented, no blank line, no top-level boundary, never depth 0
    # after an unbalanced open — must fall back to target_end (3).
    content = "    a = (\n    b,\n    c,\n    d,\n    e)\n"
    plan = eng._make_chunk_plan(content)
    assert plan["line_ranges"][0] == (1, 3)


# --- Part 4: agent-level reflection at the public entrypoint -----------------


def test_entrypoint_reflects_on_verification_error(tmp_path, monkeypatch):
    def _boom(source_file, modification_request, print_func=print):
        raise EditVerificationError(source_file, "code", "Python syntax error: bad", source_file + ".rejected")

    monkeypatch.setattr(protocol_engine, "_modify_source_code_locked", _boom)
    out = protocol_engine.modify_source_code(str(tmp_path / "x.py"), "do a thing")
    assert isinstance(out, str)
    assert "Edit rejected" in out
    assert "NOT modified" in out
    assert ".rejected" in out
    assert "text_file_str_replace_in_file" in out  # nudges toward surgical edit


# --- partial save bypasses the gate -----------------------------------------


def test_partial_save_bypasses_gate(tmp_path):
    eng = _engine(tmp_path)
    eng._modification_script_content = "x = 1\n"
    eng.chunks = ["def (broken\n"]  # invalid code
    # Partial save must NOT raise and must write a .partial sidecar (not target).
    result = eng._assemble_and_save_partial()
    assert "Task not completed" in result
    assert os.path.exists(eng.source_file + ".partial")
    assert not os.path.exists(eng.source_file)
