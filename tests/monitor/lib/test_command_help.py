"""Tests for unified command discovery (PLAN Phase 4)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from monitor.core.built_ins import configure_built_ins
from monitor.core import command_processing as cp
from monitor.lib import command_help
from monitor.lib.built_ins_utils import built_in_functions, execute_built_in_function


@pytest.fixture(autouse=True)
def _ensure_built_ins_registered():
    configure_built_ins()
    yield


def test_normalize_help_invocation_rewrites_question_mark():
    assert command_help.normalize_help_invocation("?") == ":help"
    assert command_help.normalize_help_invocation("? tools") == ":help tools"
    assert command_help.normalize_help_invocation(":?") == ":help"
    assert command_help.normalize_help_invocation("/? cost") == ":help cost"
    assert command_help.normalize_help_invocation(":help") is None
    assert command_help.normalize_help_invocation("hello") is None


def test_help_overview_groups_by_task_and_shows_examples(capsys):
    execute_built_in_function(":help")
    out = capsys.readouterr().out

    assert "Common actions:" in out
    assert ":tools" in out
    assert ":compact" in out
    assert ":break_chain" in out
    assert ":reasoning" in out
    assert ":cost_debug" in out
    assert ":reset_history" in out
    for title in ("Coding", "Repository", "Session", "Cost", "Agent", "Configuration", "Advanced"):
        assert f"=== {title} ===" in out
    assert "***" in out


def test_help_category_filter(capsys):
    execute_built_in_function(":help cost")
    out = capsys.readouterr().out
    assert "=== Cost ===" in out
    assert ":cost_debug" in out
    assert ":fuel_debug" in out
    assert ":dump_metrics" in out
    assert "=== Coding ===" not in out


def test_help_command_detail_and_examples(capsys):
    execute_built_in_function(":help tools")
    out = capsys.readouterr().out
    assert ":tools" in out
    assert "Category: coding" in out
    assert ":tools full" in out


def test_help_alias_reports_canonical_name(capsys):
    execute_built_in_function(":help cc")
    out = capsys.readouterr().out
    assert ":cc is an alias for :copy_code" in out
    assert ":copy_code" in out

    execute_built_in_function(":help model")
    out = capsys.readouterr().out
    assert ":model is an alias for :llm" in out


def test_help_search_by_substring(capsys):
    execute_built_in_function(":help compact")
    out = capsys.readouterr().out
    assert ":compact" in out


def test_built_ins_delegates_to_unified_help(capsys):
    execute_built_in_function(":built_ins session")
    out = capsys.readouterr().out
    assert "=== Session ===" in out
    assert ":break_chain" in out


def test_question_mark_shortcut_via_process_command(capsys):
    with patch.object(cp.readline, "write_history_file"), patch(
        "monitor.core.command_processing.recursive_macro_expand",
        side_effect=lambda command, *_args, **_kwargs: command,
    ):
        assert cp.process_command("?", "dummy_history") is False
    out = capsys.readouterr().out
    assert "Common actions:" in out
    assert "=== Coding ===" in out


def test_question_mark_with_query_via_evaluate_and_execute(capsys):
    result = cp.evaluate_command("? cost")
    assert result.command_type == cp.CommandType.BUILT_IN
    cp.execute_command(result, "? cost", "dummy_history")
    out = capsys.readouterr().out
    assert "=== Cost ===" in out


def test_every_public_command_is_discoverable():
    missing = [
        name
        for name in command_help.public_command_names()
        if not command_help.is_command_discoverable(name)
    ]
    assert missing == [], f"Public commands missing from help: {missing}"


def test_registered_aliases_resolve_to_canonical():
    for alias, canonical in command_help.COMMAND_ALIASES.items():
        assert command_help.canonical_command_name(alias) == canonical
        text = command_help.format_help(alias)
        assert f":{canonical}" in text


def test_help_and_question_registered_in_built_ins():
    names = {item.get("command") for item in built_in_functions}
    assert "help" in names
    assert "?" in names
