"""Tests for Phase 7 tool failure hygiene and path-scoped read budget."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from monitor.lib import tool_failures
from monitor.core import tooling


@pytest.fixture(autouse=True)
def _reset_hygiene():
    tool_failures.reset_tool_hygiene_state()
    yield
    tool_failures.reset_tool_hygiene_state()


def test_categorize_missing_match():
    assert (
        tool_failures.categorize_failure(
            tool="text_file_str_replace_in_file",
            result={"ok": False, "error": "String not found in foo.py: 'x'"},
        )
        == tool_failures.CATEGORY_MISSING_MATCH
    )


def test_format_actionable_error_includes_recovery():
    msg = tool_failures.format_actionable_error(
        tool_failures.CATEGORY_MISSING_MATCH,
        tool="text_file_str_replace_in_file",
        detail="String not found",
    )
    assert "[missing_match]" in msg
    assert "Recovery:" in msg
    assert "Re-read" in msg


def test_enrich_tool_failure_rewrites_ok_false_dict():
    result, error = tool_failures.enrich_tool_failure(
        "text_file_str_replace_in_file",
        result={"ok": False, "path": "a.py", "error": "String not found in a.py: 'zzz'"},
    )
    assert error is None
    assert result["ok"] is False
    assert result["failure_category"] == tool_failures.CATEGORY_MISSING_MATCH
    assert "[missing_match]" in result["error"]
    assert "Recovery:" in result["error"]


def test_exact_repeat_rejects_after_threshold(monkeypatch):
    monkeypatch.setattr("monitor.config.MAX_REPEATED_TOOL_CALLS", 3, raising=False)
    args = {"path": "a.py", "old_str": "x", "new_str": "y"}
    assert tool_failures.check_exact_repeat("text_file_str_replace_in_file", args) is None
    assert tool_failures.check_exact_repeat("text_file_str_replace_in_file", args) is None
    reject = tool_failures.check_exact_repeat("text_file_str_replace_in_file", args)
    assert reject is not None
    assert "[loop_rejected]" in reject


def test_path_read_budget_blocks_sliding_ranges(monkeypatch):
    monkeypatch.setattr("monitor.config.MAX_PATH_READS_PER_TURN", 3, raising=False)
    path = "/tmp/hunt.py"
    assert tool_failures.check_path_read_budget("cat_file_range", {"path": path, "start_line": 1, "end_line": 40}) is None
    assert tool_failures.check_path_read_budget("cat_file_range", {"path": path, "start_line": 41, "end_line": 80}) is None
    assert tool_failures.check_path_read_budget("cat_file_range", {"path": path, "start_line": 81, "end_line": 120}) is None
    reject = tool_failures.check_path_read_budget(
        "cat_file_range", {"path": path, "start_line": 121, "end_line": 160}
    )
    assert reject is not None
    assert "[read_budget]" in reject
    assert "ripgrep" in reject.lower()


def test_path_read_budget_is_per_path(monkeypatch):
    monkeypatch.setattr("monitor.config.MAX_PATH_READS_PER_TURN", 2, raising=False)
    assert tool_failures.check_path_read_budget("cat_file", {"path": "a.py"}) is None
    assert tool_failures.check_path_read_budget("cat_file", {"path": "a.py"}) is None
    assert tool_failures.check_path_read_budget("cat_file", {"path": "b.py"}) is None
    reject_a = tool_failures.check_path_read_budget("cat_file", {"path": "a.py"})
    assert reject_a is not None
    assert "a.py" in reject_a


def test_execute_tool_call_enforces_read_budget(monkeypatch):
    monkeypatch.setattr("monitor.config.MAX_PATH_READS_PER_TURN", 2, raising=False)
    monkeypatch.setattr("monitor.config.MAX_REPEATED_TOOL_CALLS", 0, raising=False)
    fake = MagicMock(return_value="file contents")
    with patch.dict(tooling.AVAILABLE_TOOLS, {"cat_file_range": fake}, clear=False):
        for start in (1, 50):
            result, error = tooling.execute_tool_call(
                {
                    "function": {
                        "name": "cat_file_range",
                        "arguments": {
                            "path": "hunt.py",
                            "start_line": start,
                            "end_line": start + 40,
                        },
                    }
                }
            )
            assert error is None
            assert result == "file contents"
        result, error = tooling.execute_tool_call(
            {
                "function": {
                    "name": "cat_file_range",
                    "arguments": {
                        "path": "hunt.py",
                        "start_line": 100,
                        "end_line": 140,
                    },
                }
            }
        )
    assert result is None
    assert error is not None
    assert "[read_budget]" in error
    assert fake.call_count == 2


def test_execute_tool_call_enriches_failed_replace(monkeypatch):
    monkeypatch.setattr("monitor.config.MAX_REPEATED_TOOL_CALLS", 0, raising=False)
    monkeypatch.setattr("monitor.config.MAX_PATH_READS_PER_TURN", 0, raising=False)

    def _fail(**_kwargs):
        return {"ok": False, "path": "a.py", "error": "String not found in a.py: 'nope'"}

    with patch.dict(tooling.AVAILABLE_TOOLS, {"text_file_str_replace_in_file": _fail}, clear=False):
        result, error = tooling.execute_tool_call(
            {
                "function": {
                    "name": "text_file_str_replace_in_file",
                    "arguments": {
                        "command": "str_replace",
                        "path": "a.py",
                        "old_str": "nope",
                        "new_str": "yes",
                    },
                }
            }
        )
    assert error is None
    assert result["ok"] is False
    assert "[missing_match]" in result["error"]
    assert "Recovery:" in result["error"]


def test_record_nl_edit_increments_and_notices_once(capsys, monkeypatch):
    monkeypatch.setattr("monitor.config.SESSION_NL_EDIT_COUNT", 0, raising=False)
    tool_failures.record_edit_tool_usage("modify_source_code")
    tool_failures.record_edit_tool_usage("modify_source_code")
    out = capsys.readouterr().out
    assert out.count("[notice] Using modify_source_code") == 1
    from monitor import config

    assert config.SESSION_NL_EDIT_COUNT == 2


def test_preferred_edit_order_text():
    text = tool_failures.preferred_edit_order_text()
    assert "text_file_create" in text
    assert text.index("text_file_create") < text.index("modify_source_code")
