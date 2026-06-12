import pytest
import unittest
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch, MagicMock
import io
import copy
import sys

import monitor.core.built_ins as built_ins
import monitor.lib.built_in_commands as bic

class TestConfigureBuiltIns(unittest.TestCase):
    @patch('monitor.lib.built_in_commands.print_colored_error')
    def test_compact_rejects_arguments(self, mock_error):
        built_ins.compact_command("unexpected")
        mock_error.assert_called_once_with(":compact does not accept arguments.")

    @patch('monitor.lib.built_in_commands.logger')
    @patch('monitor.lib.built_in_commands.print')
    @patch('monitor.lib.built_in_commands.config')
    def test_compact_runs_partial_preserve_flow(
        self,
        mock_config,
        mock_print,
        mock_logger,
    ):
        mock_config.CONVERSATION_HISTORY = [
            {"role": "user", "content": "older"},
            {"role": "assistant", "content": "older reply"},
            {"role": "user", "content": "recent"},
            {"role": "assistant", "content": "recent reply"},
        ]
        mock_config.RECENT_TURNS_PRESERVED_ON_COMPACT = 1
        mock_config.SUMMARIZATION_CONFIG = {"prompt": {"template": "x"}, "triggers": {}}
        mock_config.MODEL = "test-model"
        mock_config.SESSION_ID = "session-1"
        mock_config.SESSION_COMPACTION_COUNT = 0

        mock_split = MagicMock(return_value=2)
        mock_generate = MagicMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="summary text"))]
            )
        )
        mock_reset = MagicMock()
        fake_rate_limiter = SimpleNamespace(RATE_LIMITER=MagicMock())
        fake_litellm = SimpleNamespace(completion=MagicMock())

        with patch.dict(
            sys.modules,
            {
                "monitor.lib.history": SimpleNamespace(
                    _find_compaction_split_index=mock_split,
                    generate_conversation_summary=mock_generate,
                    reset_conversation_with_partial_summary=mock_reset,
                ),
                "monitor.lib.token_management": SimpleNamespace(count_message_tokens=MagicMock()),
                "monitor.lib.rate_limiter": fake_rate_limiter,
                "litellm": fake_litellm,
            },
        ), patch(
            "monitor.lib.built_in_commands.build_system_prompt",
            return_value="system prompt",
            create=True,
        ):
            built_ins.compact_command()

        mock_generate.assert_called_once()
        mock_reset.assert_called_once()
        reset_args = mock_reset.call_args.args
        self.assertEqual(reset_args[0], "summary text")
        self.assertEqual(
            reset_args[2],
            [
                {"role": "user", "content": "recent"},
                {"role": "assistant", "content": "recent reply"},
            ],
        )
        self.assertIs(reset_args[3], mock_config.CONVERSATION_HISTORY)
        self.assertIs(reset_args[4], mock_logger)
        self.assertIs(reset_args[5], mock_config)
        self.assertEqual(mock_config.SESSION_COMPACTION_COUNT, 1)
        mock_print.assert_called_with("Conversation compacted.")

    @patch('monitor.lib.built_in_commands.logger')
    @patch('monitor.lib.built_in_commands.print')
    @patch('monitor.lib.built_in_commands.config')
    @patch('monitor.lib.built_in_commands._find_compaction_split_index', create=True)
    def test_compact_noop_when_history_too_short(
        self,
        mock_split,
        mock_config,
        mock_print,
        mock_logger,
    ):
        mock_config.CONVERSATION_HISTORY = [{"role": "user", "content": "only"}]
        mock_config.RECENT_TURNS_PRESERVED_ON_COMPACT = 6
        mock_split.return_value = None

        built_ins.compact_command()

        mock_print.assert_called_with("Not enough history to compact yet.")
        mock_logger.info.assert_called_once()

    @patch('monitor.core.built_ins.append_function_to_built_ins')
    @patch('monitor.core.built_ins.edit_macros_command')
    def test_edit_macros_command_registration_and_invocation(self, mock_edit_macros_command, mock_append):
        """
        Test that :edit_macros is registered and that invoking it calls the correct function.
        """
        # Will store all registrations as dicts (as passed to append_function_to_built_ins)
        registrations = []
        def side_effect(reg_dict):
            registrations.append(reg_dict)
        mock_append.side_effect = side_effect

        # Run the registration
        built_ins.configure_built_ins()

        # Find the canonical edit_macros registration
        found = [d for d in registrations if d.get("command") == "edit_macros"]
        self.assertEqual(len(found), 1, "Should register edit_macros exactly once")
        macro_cmd = found[0]
        macro_func = macro_cmd["function"]

        # Call the registered function and confirm it calls edit_macros_command
        macro_func("test arg")
        mock_edit_macros_command.assert_called_once_with("test arg")

    @patch('monitor.core.built_ins.reload_macros_command')
    @patch('monitor.core.built_ins.append_function_to_built_ins')
    def test_reload_macros_command_registration_and_invocation(self, mock_append, mock_reload):
        """
        Test that :reload_macros is registered and invoking it calls core.built_ins.reload_macros_command.
        """
        registrations = []
        mock_append.side_effect = lambda reg: registrations.append(reg)

        # Run the registration
        built_ins.configure_built_ins()

        # Find the canonical reload_macros registration
        found = [r for r in registrations if r.get("command") == "reload_macros"]
        self.assertEqual(len(found), 1, "Should register reload_macros exactly once")
        reload_reg = found[0]
        reload_func = reload_reg["function"]

        # Call the registered function
        reload_func("test")
        mock_reload.assert_called_once_with("test")

    @patch('monitor.core.built_ins.append_function_to_built_ins')
    def test_wiki_lint_command_registration(self, mock_append):
        registrations = []
        mock_append.side_effect = lambda reg: registrations.append(reg)

        built_ins.configure_built_ins()

        found = [r for r in registrations if r.get("command") == "wiki_lint"]
        self.assertEqual(len(found), 1, "Should register wiki_lint exactly once")


def test_execute_built_in_function_accepts_slash_prefix_and_preserves_raw_args():
    from monitor.lib import built_ins_utils

    original_entry = next(
        item for item in built_ins_utils.built_in_functions if item.get("command") == "help"
    )
    original_function = original_entry["function"]
    mock_handler = MagicMock()
    original_entry["function"] = mock_handler
    try:
        built_ins_utils.execute_built_in_function("/help   spaced   args")
    finally:
        original_entry["function"] = original_function

    mock_handler.assert_called_once_with("spaced   args")


def test_wiki_lint_command_help_behavior(capsys):
    bic.wiki_lint_command("help")
    captured = capsys.readouterr()
    assert "wiki_lint" in captured.out
    assert "structural|semantic|all" in captured.out


@patch("monitor.lib.built_in_commands.print_colored_error")
def test_wiki_lint_command_rejects_invalid_mode(mock_error):
    bic.wiki_lint_command("unexpected")
    mock_error.assert_called_once()


@patch("monitor.lib.built_in_commands.ensure_configured_project_wiki", return_value=None)
def test_wiki_lint_command_returns_none_when_wiki_not_configured(mock_ensure, capsys):
    result = bic.wiki_lint_command("")
    captured = capsys.readouterr()

    assert result is None
    assert captured.out.strip()
    mock_ensure.assert_called_once()


@patch("monitor.lib.built_in_commands.run_project_wiki_lint_mode")
@patch("monitor.lib.built_in_commands.ensure_configured_project_wiki")
def test_wiki_lint_command_prints_report_and_returns_structured_result(
    mock_ensure,
    mock_run,
    capsys,
):
    mock_ensure.return_value = "/tmp/wiki"
    sample_result = {
        "mode": "structural",
        "report": "Wiki lint report\n- issue 1",
        "issues": [{"path": "page.md", "message": "issue 1"}],
    }
    mock_run.return_value = sample_result

    result = bic.wiki_lint_command("")

    captured = capsys.readouterr()
    assert result == sample_result
    assert "Wiki lint report" in captured.out
    mock_ensure.assert_called_once()
    mock_run.assert_called_once_with("/tmp/wiki", "structural")


@patch("monitor.lib.built_in_commands.run_project_wiki_lint_mode")
@patch("monitor.lib.built_in_commands.ensure_configured_project_wiki")
def test_wiki_lint_command_defaults_to_structural_mode(
    mock_ensure,
    mock_run,
    capsys,
):
    mock_ensure.return_value = "/tmp/wiki"
    mock_run.return_value = {"mode": "structural", "report": "Wiki lint report\nPASS"}

    result = bic.wiki_lint_command("")

    captured = capsys.readouterr()
    assert result["mode"] == "structural"
    assert "Wiki lint report" in captured.out
    mock_run.assert_called_once_with("/tmp/wiki", "structural")


@patch("monitor.lib.built_in_commands.run_project_wiki_lint_mode")
@patch("monitor.lib.built_in_commands.ensure_configured_project_wiki")
def test_wiki_lint_command_accepts_semantic_mode(
    mock_ensure,
    mock_run,
    capsys,
):
    mock_ensure.return_value = "/tmp/wiki"
    mock_run.return_value = {"mode": "semantic", "report": "Wiki lint report\nPASS"}

    result = bic.wiki_lint_command("semantic")

    captured = capsys.readouterr()
    assert result["mode"] == "semantic"
    assert "Wiki lint report" in captured.out
    mock_run.assert_called_once_with("/tmp/wiki", "semantic")


@patch("monitor.lib.built_in_commands.run_project_wiki_lint_mode")
@patch("monitor.lib.built_in_commands.ensure_configured_project_wiki")
def test_wiki_lint_command_accepts_all_mode(
    mock_ensure,
    mock_run,
    capsys,
):
    mock_ensure.return_value = "/tmp/wiki"
    mock_run.return_value = {"mode": "all", "report": "Wiki lint report\nPASS"}

    result = bic.wiki_lint_command("all")

    captured = capsys.readouterr()
    assert result["mode"] == "all"
    assert "Wiki lint report" in captured.out
    mock_run.assert_called_once_with("/tmp/wiki", "all")


@patch("monitor.lib.built_in_commands.run_project_wiki_lint_mode")
def test_configure_built_ins_does_not_run_wiki_lint_during_registration(mock_run):
    with patch("monitor.core.built_ins.append_function_to_built_ins"):
        built_ins.configure_built_ins()

    mock_run.assert_not_called()


def test_execute_built_in_function_runs_wiki_lint_only_on_explicit_invocation():
    from monitor.lib import built_ins_utils

    built_ins.configure_built_ins()

    with patch(
        "monitor.lib.built_in_commands.ensure_configured_project_wiki",
        return_value="/tmp/wiki",
    ) as mock_ensure, patch(
        "monitor.lib.built_in_commands.run_project_wiki_lint_mode",
        return_value={"mode": "structural", "report": "Wiki lint: PASS"},
    ) as mock_run:
        built_ins_utils.execute_built_in_function(":help")
        mock_ensure.assert_not_called()
        mock_run.assert_not_called()

        built_ins_utils.execute_built_in_function(":wiki_lint")


    mock_ensure.assert_called_once()
    mock_run.assert_called_once_with("/tmp/wiki", "structural")

@patch("monitor.lib.built_in_commands.print_colored_error")
@patch("monitor.lib.built_in_commands.run_project_wiki_lint_mode", side_effect=RuntimeError("boom"))
@patch("monitor.lib.built_in_commands.ensure_configured_project_wiki")
def test_wiki_lint_command_returns_none_and_prints_error_on_linter_failure(
    mock_ensure,
    mock_run,
    mock_error,
):
    mock_ensure.return_value = "/tmp/wiki"

    result = bic.wiki_lint_command("")

    assert result is None
    mock_ensure.assert_called_once()
    mock_run.assert_called_once_with("/tmp/wiki", "structural")
    mock_error.assert_called_once()


def test_wiki_lint_command_accepts_none_argument(capsys):
    with patch("monitor.lib.built_in_commands.ensure_configured_project_wiki", return_value=None) as mock_ensure:
        result = bic.wiki_lint_command()

    captured = capsys.readouterr()
    assert result is None
    assert "No configured project wiki is available" in captured.out
    mock_ensure.assert_called_once()


def test_wiki_fix_command_help_behavior(capsys):
    bic.wiki_fix_command("help")
    captured = capsys.readouterr()
    assert "wiki_fix" in captured.out
    assert "llm <finding_id>" in captured.out


def test_wiki_fix_command_requires_stored_lint_result(capsys):
    with patch("monitor.lib.built_in_commands.latest_wiki_lint_result", return_value=None):
        result = bic.wiki_fix_command("llm some-id")

    captured = capsys.readouterr()
    assert result is None
    assert "Run :wiki_lint first" in captured.out



@patch("monitor.lib.built_in_commands.print_colored_error")
def test_wiki_fix_command_requires_llm_submode(mock_error):
    result = bic.wiki_fix_command("some-id")

    assert result is None
    mock_error.assert_called_once()

@patch("monitor.lib.built_in_commands.print_colored_error")
def test_wiki_fix_command_rejects_unknown_finding_id(mock_error):
    with patch(
        "monitor.lib.built_in_commands.latest_wiki_lint_result",
        return_value={"findings": []},
    ):
        result = bic.wiki_fix_command("llm missing-id")

    assert result is None
    mock_error.assert_called_once()


@patch("monitor.lib.built_in_commands.print_colored_error")
def test_wiki_fix_command_rejects_unsupported_finding_kind(mock_error):
    with patch(
        "monitor.lib.built_in_commands.latest_wiki_lint_result",
        return_value={
            "findings": [{"id": "abc", "kind": "broken_reference"}],
        },
    ):
        result = bic.wiki_fix_command("llm abc")

    assert result is None
    mock_error.assert_called_once()


@patch("monitor.lib.built_in_commands.litellm.completion")
def test_wiki_fix_command_previews_diff_for_semantic_stale_location_claim(
    mock_completion,
    tmp_path,
    capsys,
):
    mock_completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="The implementation location in this page is stale and must be updated."))]
    )
    wiki_dir = tmp_path / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    page_path = wiki_dir / "ARCHITECTURE.md"
    claim = "The authoritative implementation lives in src/monitor/lib/missing_server.py"
    page_path.write_text(f"{claim}\n", encoding="utf-8")
    finding = {
        "id": "semantic|ARCHITECTURE.md|src/monitor/lib/missing_server.py|claim",
        "kind": "semantic_stale_location_claim",
        "page": "ARCHITECTURE.md",
        "path": "src/monitor/lib/missing_server.py",
        "claim": claim,
        "evidence": "src/monitor/lib/missing_server.py",
    }

    with patch(
        "monitor.lib.built_in_commands.latest_wiki_lint_result",
        return_value={
            "project_dir": str(wiki_dir),
            "findings": [finding],
        },
    ):
        result = bic.wiki_fix_command(f"llm {finding['id']}")

    captured = capsys.readouterr()
    assert result is not None
    assert result["finding_id"] == finding["id"]
    assert result["page"] == "ARCHITECTURE.md"
    assert result["mode"] == "preview"
    assert result["fix_mode"] == "llm"
    assert "stale and must be updated" in result["replacement"]
    assert "--- a/" in captured.out
    assert "+++ b/" in captured.out
    mock_completion.assert_called_once()


@patch("monitor.lib.built_in_commands.print_colored_error")
@patch("monitor.lib.built_in_commands.litellm.completion")
def test_wiki_fix_command_rejects_empty_llm_replacement(mock_completion, mock_error, tmp_path):
    mock_completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=""))]
    )
    wiki_dir = tmp_path / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    page_path = wiki_dir / "ARCHITECTURE.md"
    claim = "The authoritative implementation lives in src/monitor/lib/missing_server.py"
    page_path.write_text(f"{claim}\n", encoding="utf-8")
    finding = {
        "id": "semantic|ARCHITECTURE.md|src/monitor/lib/missing_server.py|claim",
        "kind": "semantic_stale_location_claim",
        "page": "ARCHITECTURE.md",
        "path": "src/monitor/lib/missing_server.py",
        "claim": claim,
    }

    with patch(
        "monitor.lib.built_in_commands.latest_wiki_lint_result",
        return_value={"project_dir": str(wiki_dir), "findings": [finding]},
    ):
        result = bic.wiki_fix_command(f"llm {finding['id']}")

    assert result is None
    mock_error.assert_called_once()


@patch("monitor.lib.built_in_commands.print_colored_error")
@patch("monitor.lib.built_in_commands.litellm.completion")
def test_wiki_fix_command_rejects_oversized_llm_replacement(mock_completion, mock_error, tmp_path):
    mock_completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="x" * 401))]
    )
    wiki_dir = tmp_path / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    page_path = wiki_dir / "ARCHITECTURE.md"
    claim = "The authoritative implementation lives in src/monitor/lib/missing_server.py"
    page_path.write_text(f"{claim}\n", encoding="utf-8")
    finding = {
        "id": "semantic|ARCHITECTURE.md|src/monitor/lib/missing_server.py|claim",
        "kind": "semantic_stale_location_claim",
        "page": "ARCHITECTURE.md",
        "path": "src/monitor/lib/missing_server.py",
        "claim": claim,
    }

    with patch(
        "monitor.lib.built_in_commands.latest_wiki_lint_result",
        return_value={"project_dir": str(wiki_dir), "findings": [finding]},
    ):
        result = bic.wiki_fix_command(f"llm {finding['id']}")

    assert result is None
    mock_error.assert_called_once()


@patch("monitor.lib.built_in_commands.print_colored_error")
@patch("monitor.lib.built_in_commands.litellm.completion")
def test_wiki_fix_command_rejects_unchanged_llm_replacement(mock_completion, mock_error, tmp_path):
    claim = "The authoritative implementation lives in src/monitor/lib/missing_server.py"
    mock_completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=claim))]
    )
    wiki_dir = tmp_path / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    page_path = wiki_dir / "ARCHITECTURE.md"
    page_path.write_text(f"{claim}\n", encoding="utf-8")
    finding = {
        "id": "semantic|ARCHITECTURE.md|src/monitor/lib/missing_server.py|claim",
        "kind": "semantic_stale_location_claim",
        "page": "ARCHITECTURE.md",
        "path": "src/monitor/lib/missing_server.py",
        "claim": claim,
    }

    with patch(
        "monitor.lib.built_in_commands.latest_wiki_lint_result",
        return_value={"project_dir": str(wiki_dir), "findings": [finding]},
    ):
        result = bic.wiki_fix_command(f"llm {finding['id']}")

    assert result is None
    mock_error.assert_called_once()
