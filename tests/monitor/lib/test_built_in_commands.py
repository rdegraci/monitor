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

@patch("monitor.lib.built_in_commands.list_most_recent_session_folders")
@patch("monitor.lib.built_in_commands.get_sessions_root")
def test_sessions_command_prints_five_most_recent_paths(mock_root, mock_list, capsys):
    mock_root.return_value = Path("/tmp/monitor/sessions")
    mock_list.return_value = [
        Path("/tmp/monitor/sessions/5"),
        Path("/tmp/monitor/sessions/4"),
        Path("/tmp/monitor/sessions/3"),
        Path("/tmp/monitor/sessions/2"),
        Path("/tmp/monitor/sessions/1"),
    ]

    bic.sessions_command("")

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "/tmp/monitor/sessions/5",
        "/tmp/monitor/sessions/4",
        "/tmp/monitor/sessions/3",
        "/tmp/monitor/sessions/2",
        "/tmp/monitor/sessions/1",
@patch("monitor.lib.built_in_commands.list_most_recent_session_folders", return_value=[])
@patch("monitor.lib.built_in_commands.get_sessions_root")
def test_sessions_command_reports_empty_root(mock_root, mock_list, capsys):
    mock_root.return_value = Path("/tmp/monitor/sessions")

    bic.sessions_command("")

    captured = capsys.readouterr()
    assert "No session folders found under /tmp/monitor/sessions" in captured.out
    mock_list.assert_called_once_with(limit=5)


    ]
    mock_list.assert_called_once_with(limit=5)



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
    mock_run.assert_called_once_with("/tmp/wiki", "structural", None)


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
    mock_run.assert_called_once_with("/tmp/wiki", "structural", None)


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
    mock_run.assert_called_once_with("/tmp/wiki", "semantic", None)


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
    mock_run.assert_called_once_with("/tmp/wiki", "all", None)


@patch("monitor.lib.built_in_commands.run_project_wiki_lint_mode")
@patch("monitor.lib.built_in_commands.ensure_configured_project_wiki")
def test_wiki_lint_command_passes_identity_path_as_repo_root(
    mock_ensure,
    mock_run,
    capsys,
):
    from pathlib import Path

    mock_ensure.return_value = "/tmp/wiki"
    mock_run.return_value = {"mode": "structural", "report": "Wiki lint report\nPASS"}

    with patch.object(bic.config, "PROJECT_WIKI_IDENTITY_PATH", "/real/repo/root"):
        bic.wiki_lint_command("")

    mock_run.assert_called_once_with("/tmp/wiki", "structural", Path("/real/repo/root"))


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
    mock_run.assert_called_once_with("/tmp/wiki", "structural", None)


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
    mock_run.assert_called_once_with("/tmp/wiki", "structural", None)
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
    assert "apply <finding_id>" in captured.out


def test_wiki_fix_command_help_behavior_mentions_batch_modes(capsys):
    bic.wiki_fix_command("help")
    captured = capsys.readouterr()
    assert "llm_all" in captured.out
    assert "apply_all" in captured.out



def test_wiki_fix_command_help_behavior_mentions_auto_mode(capsys):
    bic.wiki_fix_command("help")
    captured = capsys.readouterr()
    assert "auto_all" in captured.out

def test_wiki_fix_command_requires_stored_lint_result(capsys):
    with patch("monitor.lib.built_in_commands.latest_wiki_lint_result", return_value=None):
        result = bic.wiki_fix_command("llm some-id")

    captured = capsys.readouterr()
    assert result is None
    assert "Run :wiki_lint first" in captured.out


@patch("monitor.lib.built_in_commands.print_colored_error")
def test_wiki_fix_command_requires_llm_submode(mock_error):
    with patch("monitor.lib.built_in_commands.latest_wiki_lint_result", return_value={"findings": []}):
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


@patch("monitor.lib.built_in_commands.litellm.completion")
def test_wiki_fix_command_previews_diff_for_semantic_stale_authority_claim(
    mock_completion,
    tmp_path,
    capsys,
):
    mock_completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="The authoritative document reference in this page is stale and must be updated."))]
    )
    wiki_dir = tmp_path / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    page_path = wiki_dir / "ARCHITECTURE.md"
    claim = "The canonical guide is docs/process/current.md"
    page_path.write_text(f"{claim}\n", encoding="utf-8")
    finding = {
        "id": "semantic|ARCHITECTURE.md|docs/process/current.md|claim",
        "kind": "semantic_stale_authority_claim",
        "page": "ARCHITECTURE.md",
        "path": "docs/process/current.md",
        "claim": claim,
        "evidence": "docs/process/current.md",
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
    assert "authoritative document reference" in result["replacement"]
    assert "--- a/" in captured.out
    assert "+++ b/" in captured.out
    mock_completion.assert_called_once()


@patch("monitor.lib.built_in_commands.litellm.completion")
def test_wiki_fix_command_previews_diff_for_semantic_stale_workflow_claim(
    mock_completion,
    tmp_path,
    capsys,
):
    mock_completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="The workflow document reference in this page is stale and must be updated."))]
    )
    wiki_dir = tmp_path / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    page_path = wiki_dir / "ARCHITECTURE.md"
    claim = "Build steps are in docs/build/current.md"
    page_path.write_text(f"{claim}\n", encoding="utf-8")
    finding = {
        "id": "semantic|ARCHITECTURE.md|docs/build/current.md|claim",
        "kind": "semantic_stale_workflow_claim",
        "page": "ARCHITECTURE.md",
        "path": "docs/build/current.md",
        "claim": claim,
        "evidence": "docs/build/current.md",
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
    assert "workflow document reference" in result["replacement"]
    assert "--- a/" in captured.out
    assert "+++ b/" in captured.out
    mock_completion.assert_called_once()


@patch("monitor.lib.built_in_commands.litellm.completion")
def test_wiki_fix_command_previews_diff_for_semantic_stale_ownership_claim(
    mock_completion,
    tmp_path,
    capsys,
):
    mock_completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="The ownership reference in this page is stale and must be updated."))]
    )
    wiki_dir = tmp_path / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    page_path = wiki_dir / "ARCHITECTURE.md"
    claim = "Changes belong in src/monitor/lib/ownership_router.py"
    page_path.write_text(f"{claim}\n", encoding="utf-8")
    finding = {
        "id": "semantic|ARCHITECTURE.md|src/monitor/lib/ownership_router.py|claim",
        "kind": "semantic_stale_ownership_claim",
        "page": "ARCHITECTURE.md",
        "path": "src/monitor/lib/ownership_router.py",
        "claim": claim,
        "evidence": "src/monitor/lib/ownership_router.py",
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
    assert "ownership reference" in result["replacement"]
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


@patch("monitor.lib.built_in_commands.litellm.completion")
def test_wiki_fix_command_apply_writes_previewed_text_to_disk(
    mock_completion,
    tmp_path,
    capsys,
):
    replacement = "The implementation location described here is stale and must be updated."
    mock_completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=replacement))]
    )
    wiki_dir = tmp_path / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    page_path = wiki_dir / "ARCHITECTURE.md"
    claim = "The authoritative implementation lives in src/monitor/lib/missing_server.py"
    page_path.write_text(f"Before\n{claim}\nAfter\n", encoding="utf-8")
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
        return_value={"project_dir": str(wiki_dir), "findings": [finding]},
    ):
        preview_result = bic.wiki_fix_command(f"llm {finding['id']}")
        result = bic.wiki_fix_command(f"apply {finding['id']}")

    captured = capsys.readouterr()
    assert preview_result is not None
    assert result is not None
    assert result["mode"] == "apply"
    assert result["page_path"] == str(page_path)
    assert result["replacement"] == preview_result["replacement"]
    assert "Applied wiki fix" in captured.out
    assert replacement in page_path.read_text(encoding="utf-8")
    assert claim not in page_path.read_text(encoding="utf-8")
    mock_completion.assert_called_once()


@patch("monitor.lib.built_in_commands.litellm.completion")
def test_wiki_fix_command_apply_writes_previewed_ownership_text_to_disk(
    mock_completion,
    tmp_path,
    capsys,
):
    replacement = "The ownership reference described here is stale and must be updated."
    mock_completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=replacement))]
    )
    wiki_dir = tmp_path / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    page_path = wiki_dir / "ARCHITECTURE.md"
    claim = "Changes belong in src/monitor/lib/ownership_router.py"
    page_path.write_text(f"Before\n{claim}\nAfter\n", encoding="utf-8")
    finding = {
        "id": "semantic|ARCHITECTURE.md|src/monitor/lib/ownership_router.py|claim",
        "kind": "semantic_stale_ownership_claim",
        "page": "ARCHITECTURE.md",
        "path": "src/monitor/lib/ownership_router.py",
        "claim": claim,
        "evidence": "src/monitor/lib/ownership_router.py",
    }

    with patch(
        "monitor.lib.built_in_commands.latest_wiki_lint_result",
        return_value={"project_dir": str(wiki_dir), "findings": [finding]},
    ):
        preview_result = bic.wiki_fix_command(f"llm {finding['id']}")
        result = bic.wiki_fix_command(f"apply {finding['id']}")

    captured = capsys.readouterr()
    assert preview_result is not None
    assert result is not None
    assert result["mode"] == "apply"
    assert result["page_path"] == str(page_path)
    assert result["replacement"] == preview_result["replacement"]
    assert "Applied wiki fix" in captured.out
    assert replacement in page_path.read_text(encoding="utf-8")
    assert claim not in page_path.read_text(encoding="utf-8")
    mock_completion.assert_called_once()


@patch("monitor.lib.built_in_commands.print_colored_error")
def test_wiki_fix_command_apply_requires_stored_preview(mock_error, tmp_path):
    wiki_dir = tmp_path / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    page_path = wiki_dir / "ARCHITECTURE.md"
    claim = "The authoritative implementation lives in src/monitor/lib/missing_server.py"
    page_path.write_text(f"{claim}\n", encoding="utf-8")
    finding = {
        "id": "semantic|ARCHITECTURE.md|src/monitor/lib/missing_server.py|claim-no-preview",
        "kind": "semantic_stale_location_claim",
        "page": "ARCHITECTURE.md",
        "path": "src/monitor/lib/missing_server.py",
        "claim": claim,
        "evidence": "src/monitor/lib/missing_server.py",
    }

    with patch(
        "monitor.lib.built_in_commands.latest_wiki_lint_result",
        return_value={"project_dir": str(wiki_dir), "findings": [finding]},
    ):
        result = bic.wiki_fix_command(f"apply {finding['id']}")

    assert result is None
    mock_error.assert_called_once()


@patch("monitor.lib.built_in_commands.litellm.completion")
def test_wiki_fix_command_llm_all_previews_all_supported_findings(
    mock_completion,
    tmp_path,
    capsys,
):
    mock_completion.side_effect = [
        MagicMock(choices=[MagicMock(message=MagicMock(content="The implementation location in this page is stale and must be updated."))]),
        MagicMock(choices=[MagicMock(message=MagicMock(content="The workflow document reference in this page is stale and must be updated."))]),
    ]
    wiki_dir = tmp_path / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    location_claim = "The authoritative implementation lives in src/monitor/lib/missing_server.py"
    workflow_claim = "Build steps are in docs/build/current.md"
    page_path = wiki_dir / "ARCHITECTURE.md"
    page_path.write_text(f"{location_claim}\n{workflow_claim}\n", encoding="utf-8")
    findings = [
        {
            "id": "semantic|ARCHITECTURE.md|src/monitor/lib/missing_server.py|claim",
            "kind": "semantic_stale_location_claim",
            "page": "ARCHITECTURE.md",
            "path": "src/monitor/lib/missing_server.py",
            "claim": location_claim,
            "evidence": "src/monitor/lib/missing_server.py",
        },
        {
            "id": "broken|ARCHITECTURE.md|OTHER.md|claim",
            "kind": "broken_reference",
            "page": "ARCHITECTURE.md",
            "path": "OTHER.md",
        },
        {
            "id": "semantic|ARCHITECTURE.md|docs/build/current.md|claim",
            "kind": "semantic_stale_workflow_claim",
            "page": "ARCHITECTURE.md",
            "path": "docs/build/current.md",
            "claim": workflow_claim,
            "evidence": "docs/build/current.md",
        },
    ]

    with patch(
        "monitor.lib.built_in_commands.latest_wiki_lint_result",
        return_value={"project_dir": str(wiki_dir), "findings": findings},
    ):
        result = bic.wiki_fix_command("llm_all")

    captured = capsys.readouterr()
    assert result is not None
    assert result["mode"] == "preview_all"
    assert result["supported_count"] == 2
    assert result["previewed_count"] == 2
    assert len(result["results"]) == 2
    assert captured.out.count("--- a/") == 2
    assert mock_completion.call_count == 2


@patch("monitor.lib.built_in_commands.print_colored_error")
def test_wiki_fix_command_apply_all_requires_stored_previews(mock_error, tmp_path):
    wiki_dir = tmp_path / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    claim = "The authoritative implementation lives in src/monitor/lib/missing_server.py"
    page_path = wiki_dir / "ARCHITECTURE.md"
    page_path.write_text(f"{claim}\n", encoding="utf-8")
    findings = [
        {
            "id": "semantic|ARCHITECTURE.md|src/monitor/lib/missing_server.py|claim-missing-preview",
            "kind": "semantic_stale_location_claim",
            "page": "ARCHITECTURE.md",
            "path": "src/monitor/lib/missing_server.py",
            "claim": claim,
            "evidence": "src/monitor/lib/missing_server.py",
        }
    ]

    with patch(
        "monitor.lib.built_in_commands.latest_wiki_lint_result",
        return_value={"project_dir": str(wiki_dir), "findings": findings},
    ):
        result = bic.wiki_fix_command("apply_all")

    assert result is None
    mock_error.assert_called_once()
    assert "llm_all" in mock_error.call_args[0][0]


@patch("monitor.lib.built_in_commands.litellm.completion")
def test_wiki_fix_command_apply_all_applies_all_supported_previews(
    mock_completion,
    tmp_path,
    capsys,
):
    mock_completion.side_effect = [
        MagicMock(choices=[MagicMock(message=MagicMock(content="The implementation location in this page is stale and must be updated."))]),
        MagicMock(choices=[MagicMock(message=MagicMock(content="The workflow document reference in this page is stale and must be updated."))]),
    ]
    wiki_dir = tmp_path / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    page_one = wiki_dir / "ARCHITECTURE.md"
    page_two = wiki_dir / "BUILD.md"
    location_claim = "The authoritative implementation lives in src/monitor/lib/missing_server.py"
    workflow_claim = "Build steps are in docs/build/current.md"
    page_one.write_text(f"Before\n{location_claim}\nAfter\n", encoding="utf-8")
    page_two.write_text(f"Before\n{workflow_claim}\nAfter\n", encoding="utf-8")
    findings = [
        {
            "id": "semantic|ARCHITECTURE.md|src/monitor/lib/missing_server.py|claim",
            "kind": "semantic_stale_location_claim",
            "page": "ARCHITECTURE.md",
            "path": "src/monitor/lib/missing_server.py",
            "claim": location_claim,
            "evidence": "src/monitor/lib/missing_server.py",
        },
        {
            "id": "semantic|BUILD.md|docs/build/current.md|claim",
            "kind": "semantic_stale_workflow_claim",
            "page": "BUILD.md",
            "path": "docs/build/current.md",
            "claim": workflow_claim,
            "evidence": "docs/build/current.md",
        },
    ]

    with patch(
        "monitor.lib.built_in_commands.latest_wiki_lint_result",
        return_value={"project_dir": str(wiki_dir), "findings": findings},
    ):
        preview_result = bic.wiki_fix_command("llm_all")
        result = bic.wiki_fix_command("apply_all")

    captured = capsys.readouterr()
    assert preview_result is not None
    assert result is not None
    assert result["mode"] == "apply_all"
    assert result["supported_count"] == 2
    assert result["applied_count"] == 2
    assert len(result["results"]) == 2
    assert location_claim not in page_one.read_text(encoding="utf-8")
    assert workflow_claim not in page_two.read_text(encoding="utf-8")
    assert "Applied wiki fix" in captured.out
    assert mock_completion.call_count == 2


@patch("monitor.lib.built_in_commands.litellm.completion")
def test_wiki_fix_command_auto_all_previews_then_applies_supported_findings(
    mock_completion,
    tmp_path,
    capsys,
):
    mock_completion.side_effect = [
        MagicMock(choices=[MagicMock(message=MagicMock(content="The implementation location in this page is stale and must be updated."))]),
        MagicMock(choices=[MagicMock(message=MagicMock(content="The workflow document reference in this page is stale and must be updated."))]),
    ]
    wiki_dir = tmp_path / "docs" / "cache"
    wiki_dir.mkdir(parents=True)
    page_one = wiki_dir / "ARCHITECTURE.md"
    page_two = wiki_dir / "BUILD.md"
    location_claim = "The authoritative implementation lives in src/monitor/lib/missing_server.py"
    workflow_claim = "Build steps are in docs/build/current.md"
    page_one.write_text(f"Before\n{location_claim}\nAfter\n", encoding="utf-8")
    page_two.write_text(f"Before\n{workflow_claim}\nAfter\n", encoding="utf-8")
    findings = [
        {
            "id": "semantic|ARCHITECTURE.md|src/monitor/lib/missing_server.py|claim-auto",
            "kind": "semantic_stale_location_claim",
            "page": "ARCHITECTURE.md",
            "path": "src/monitor/lib/missing_server.py",
            "claim": location_claim,
            "evidence": "src/monitor/lib/missing_server.py",
        },
        {
            "id": "broken|ARCHITECTURE.md|OTHER.md|claim-auto",
            "kind": "broken_reference",
            "page": "ARCHITECTURE.md",
            "path": "OTHER.md",
        },
        {
            "id": "semantic|BUILD.md|docs/build/current.md|claim-auto",
            "kind": "semantic_stale_workflow_claim",
            "page": "BUILD.md",
            "path": "docs/build/current.md",
            "claim": workflow_claim,
            "evidence": "docs/build/current.md",
        },
    ]

    with patch(
        "monitor.lib.built_in_commands.latest_wiki_lint_result",
        return_value={"project_dir": str(wiki_dir), "findings": findings},
    ):
        result = bic.wiki_fix_command("auto_all")

    captured = capsys.readouterr()
    assert result is not None
    assert result["mode"] == "auto_all"
    assert result["supported_count"] == 2
    assert result["previewed_count"] == 2
    assert result["applied_count"] == 2
    assert len(result["preview_results"]) == 2
    assert len(result["apply_results"]) == 2
    assert location_claim not in page_one.read_text(encoding="utf-8")
    assert workflow_claim not in page_two.read_text(encoding="utf-8")
    assert captured.out.count("--- a/") == 4
    assert "Applied wiki fix" in captured.out
    assert mock_completion.call_count == 2


def _wiki_init_env(tmp_path, monkeypatch):
    """Configure a tmp repo + appdir wiki and return (repo, wiki_dir, index)."""
    repo = tmp_path / "realrepo"
    (repo / "src" / "monitor").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname = "monitor3"\n', encoding="utf-8")
    (repo / "README.md").write_text("# monitor3\nAn LLM harness.\n", encoding="utf-8")

    wiki_dir = tmp_path / "appdir" / "monitor-wiki" / "slug"
    wiki_dir.mkdir(parents=True)

    monkeypatch.setattr(bic.config, "PROJECT_WIKI_IDENTITY_PATH", str(repo))
    monkeypatch.setattr(bic.config, "PROJECT_WIKI_PATH", str(wiki_dir))
    monkeypatch.setattr(bic.config, "MODEL", "test-model")
    return repo, wiki_dir, wiki_dir / "INDEX.md"


_WIKI_INIT_DRAFT = "# Project Wiki Index\n\n## Overview\n- monitor3 is an LLM harness; see src/monitor.\n"


def test_wiki_init_command_help_behavior(capsys):
    result = bic.wiki_init_command("help")

    captured = capsys.readouterr()
    assert result is None
    assert "wiki_init" in captured.out
    assert "apply" in captured.out


def test_wiki_init_command_no_project_wiki(monkeypatch, capsys):
    monkeypatch.setattr(bic.config, "PROJECT_WIKI_PATH", None)
    result = bic.wiki_init_command("")

    captured = capsys.readouterr()
    assert result is None
    assert "No configured project wiki" in captured.out


def test_wiki_init_command_preview_drafts_without_writing(tmp_path, monkeypatch, capsys):
    repo, wiki_dir, index = _wiki_init_env(tmp_path, monkeypatch)

    with patch.object(bic, "litellm") as mock_litellm:
        mock_litellm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=_WIKI_INIT_DRAFT))]
        )
        result = bic.wiki_init_command("")

    captured = capsys.readouterr()
    assert result is not None
    assert result["mode"] == "preview"
    assert "monitor3 is an LLM harness" in captured.out
    # The on-disk INDEX.md is still the auto-provisioned placeholder, not the draft.
    assert "monitor3 is an LLM harness" not in index.read_text(encoding="utf-8")


def test_wiki_init_command_strips_code_fences(tmp_path, monkeypatch):
    repo, wiki_dir, index = _wiki_init_env(tmp_path, monkeypatch)
    fenced = "```markdown\n" + _WIKI_INIT_DRAFT + "```\n"

    with patch.object(bic, "litellm") as mock_litellm:
        mock_litellm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=fenced))]
        )
        result = bic.wiki_init_command("")

    assert result["content"].startswith("# Project Wiki Index")
    assert "```" not in result["content"]


def test_wiki_init_command_apply_writes_when_placeholder(tmp_path, monkeypatch, capsys):
    repo, wiki_dir, index = _wiki_init_env(tmp_path, monkeypatch)

    with patch.object(bic, "litellm") as mock_litellm:
        mock_litellm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=_WIKI_INIT_DRAFT))]
        )
        bic.wiki_init_command("")
        result = bic.wiki_init_command("apply")

    captured = capsys.readouterr()
    assert result["mode"] == "apply"
    assert result["written"] is True
    assert result["forced"] is False
    assert "monitor3 is an LLM harness" in index.read_text(encoding="utf-8")
    assert "Wrote drafted INDEX.md" in captured.out


def test_wiki_init_command_apply_refuses_when_substantive_without_force(
    tmp_path, monkeypatch
):
    repo, wiki_dir, index = _wiki_init_env(tmp_path, monkeypatch)
    index.write_text(
        "# Project Wiki Index\n\n## Overview\n- Hand-written, important content.\n",
        encoding="utf-8",
    )

    with patch.object(bic, "litellm") as mock_litellm, patch.object(
        bic, "print_colored_error"
    ) as mock_error:
        mock_litellm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=_WIKI_INIT_DRAFT))]
        )
        bic.wiki_init_command("")
        result = bic.wiki_init_command("apply")

    assert result is None
    mock_error.assert_called_once()
    # Existing content is preserved.
    assert "Hand-written, important content." in index.read_text(encoding="utf-8")


def test_wiki_init_command_apply_force_overwrites_substantive(tmp_path, monkeypatch):
    repo, wiki_dir, index = _wiki_init_env(tmp_path, monkeypatch)
    index.write_text(
        "# Project Wiki Index\n\n## Overview\n- Old content.\n", encoding="utf-8"
    )

    with patch.object(bic, "litellm") as mock_litellm:
        mock_litellm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=_WIKI_INIT_DRAFT))]
        )
        bic.wiki_init_command("")
        result = bic.wiki_init_command("apply force")

    assert result["forced"] is True
    text = index.read_text(encoding="utf-8")
    assert "monitor3 is an LLM harness" in text
    assert "Old content." not in text


def test_wiki_init_command_apply_without_draft_errors(tmp_path, monkeypatch):
    repo, wiki_dir, index = _wiki_init_env(tmp_path, monkeypatch)

    with patch.object(bic, "latest_wiki_init_draft", return_value=None), patch.object(
        bic, "print_colored_error"
    ) as mock_error:
        result = bic.wiki_init_command("apply")

    assert result is None
    mock_error.assert_called_once()


def test_wiki_init_command_rejects_invalid_arg(tmp_path, monkeypatch):
    repo, wiki_dir, index = _wiki_init_env(tmp_path, monkeypatch)

    with patch.object(bic, "print_colored_error") as mock_error:
        result = bic.wiki_init_command("bogus")

    assert result is None
    mock_error.assert_called_once()


def test_build_repo_orientation_context_is_bounded_and_high_signal(tmp_path):
    from monitor.lib.built_ins_wiki_utils import build_repo_orientation_context

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    (repo / "README.md").write_text("# x\nhello\n", encoding="utf-8")

    context = build_repo_orientation_context(repo)

    assert "Top-level entries:" in context
    assert "src/" in context
    assert "pyproject.toml" in context
    assert "README.md" in context
    assert len(context) <= 8100  # bounded
