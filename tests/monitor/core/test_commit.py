import importlib
import unittest
from unittest.mock import MagicMock, patch

import monitor.core.commit as commit
from monitor.lib import llm_utils


class TestCommitCommand(unittest.TestCase):
    @patch("os.unlink")  # <-- Add this at the top of the decorator list
    @patch("monitor.core.commit.get_suggested_commit_message")
    @patch("monitor.core.commit.get_staged_diff")
    @patch("monitor.core.commit.input")
    @patch("monitor.core.commit.tempfile.NamedTemporaryFile")
    @patch("monitor.core.commit.perform_git_commit")
    def test_make_commit_command_happy_path(
        self,
        mock_perform_git_commit,
        mock_tmpfile,
        mock_input,
        mock_get_staged_diff,
        mock_get_message,
        mock_unlink,
    ):
        """Happy path with 'y' uses suggested message and prints success."""
        mock_get_staged_diff.return_value = "diff --git ..."
        mock_get_message.return_value = "Add new feature"
        mock_input.return_value = "y"

        # Mock tempfile.NamedTemporaryFile to fake file handling
        mock_file = MagicMock()
        mock_file.name = "tempfile"
        mock_tmpfile.return_value.__enter__.return_value = mock_file

        # Dynamically import yellow and reset from monitor.lib.colors
        colors = importlib.import_module("monitor.lib.colors")
        yellow = getattr(colors, "yellow")
        reset = getattr(colors, "reset")

        outputs = []

        def capprint(msg, *a, **k):
            outputs.append(str(msg))

        commit.make_commit_command(print_func=capprint)

        mock_perform_git_commit.assert_called_once_with("Add new feature")
        combined_printed = "\n".join(outputs)
        assert (
            "✅ Commit created successfully" in combined_printed
        ), "The commit success message was not printed. Captured: %s" % outputs

    @patch("monitor.core.commit.get_staged_diff", return_value="")
    def test_make_commit_command_no_staged_changes(self, mock_get_staged_diff):
        """No staged changes prints friendly message and no commit."""
        colors = importlib.import_module("monitor.lib.colors")
        yellow = getattr(colors, "yellow")
        reset = getattr(colors, "reset")

        outputs = []

        def capprint(msg, *a, **k):
            outputs.append(str(msg))

        commit.make_commit_command(print_func=capprint)
        combined_printed = "\n".join(outputs)
        assert (
            "No staged changes to commit. Please stage changes first." in combined_printed
        ), "The 'no staged changes' message was not printed. Captured: %s" % outputs

    @patch("monitor.core.commit.perform_git_diff_staged")
    def test_get_staged_diff_proxies_and_returns(self, mock_diff):
        """get_staged_diff proxies args and returns underlying diff."""
        mock_diff.return_value = "some diff"
        result = commit.get_staged_diff(silent=False)
        self.assertEqual(result, "some diff")
        mock_diff.assert_called_once_with(silent=False)

    @patch("monitor.core.commit.perform_git_diff_staged", side_effect=Exception("boom"))
    def test_get_staged_diff_raises(self, mock_diff):
        """get_staged_diff raises when underlying diff function raises."""
        with self.assertRaises(Exception):
            commit.get_staged_diff(silent=True)

    @patch("monitor.core.commit.llm_utils.call_litellm_completion")
    @patch("monitor.core.commit.build_commit_message_query_input")
    def test_get_suggested_commit_message_builds_and_completes(
        self, mock_build, mock_completion
    ):
        """Builder is called and the stateless completion result is returned."""
        mock_build.return_value = "query_input"
        message = MagicMock()
        message.content = "Suggested commit"
        mock_completion.return_value.choices = [MagicMock(message=message)]
        diff = "diff --git ..."

        result = commit.get_suggested_commit_message(diff)

        self.assertEqual(result, "Suggested commit")
        self.assertTrue(mock_build.called)
        _, kwargs = mock_build.call_args
        self.assertEqual(kwargs.get("diff"), diff)
        # Uses a stateless completion, not the history-mutating query().
        self.assertFalse(hasattr(commit, "query"))
        self.assertTrue(mock_completion.called)

    @patch("monitor.core.commit.llm_utils.call_litellm_completion")
    @patch("monitor.core.commit.build_commit_message_query_input")
    def test_get_suggested_commit_message_uses_commit_reasoning_overrides(
        self, mock_build, mock_completion
    ):
        """Commit generation should honor commit-specific reasoning overrides."""
        mock_build.return_value = "query_input"
        message = MagicMock()
        message.content = "Suggested commit"
        mock_completion.return_value.choices = [MagicMock(message=message)]

        with patch.object(commit.config, "COMMIT_MODEL", "openai/gpt-5.4"), patch.object(
            commit.config, "COMMIT_REASONING_EFFORT", "high"
        ), patch.object(
            commit.config, "COMMIT_REASONING_MAX_COMPLETION_TOKENS", 8000
        ), patch.object(commit.config, "REASONING_MODEL_PREFIX", "openai/gpt-5"):
            result = commit.get_suggested_commit_message("diff --git ...")

        self.assertEqual(result, "Suggested commit")

    @patch("monitor.core.commit.llm_utils.call_litellm_completion")
    @patch("monitor.core.commit.build_commit_message_query_input")
    def test_get_suggested_commit_message_routes_ollama_to_native_completion(
        self, mock_build, mock_completion
    ):
        """Ollama commit messages should go through the native adapter path."""
        from monitor import config

        config.COMMIT_MODEL = "ollama/ornith:9b"
        config.MODEL = "ollama/ornith:9b"
        config.REASONING_MODEL_PREFIX = "openai/gpt-5"
        config.COMMIT_REASONING_EFFORT = None
        config.COMMIT_REASONING_MAX_COMPLETION_TOKENS = None
        mock_build.return_value = "query_input"
        message = MagicMock()
        message.content = "Suggested commit"
        mock_completion.return_value.choices = [MagicMock(message=message)]

        result = commit.get_suggested_commit_message("diff --git ...")

        self.assertEqual(result, "Suggested commit")
        kwargs = mock_completion.call_args.kwargs
        self.assertEqual(kwargs.get("tool_descriptions"), [])
        self.assertEqual(kwargs.get("gemini_tool_descriptions"), [])

    @patch("os.unlink")
    @patch("monitor.core.commit.subprocess.run")
    @patch("monitor.core.commit.perform_git_commit")
    @patch("monitor.core.commit.tempfile.NamedTemporaryFile")
    @patch("monitor.core.commit.get_suggested_commit_message", return_value="msg")
    @patch("monitor.core.commit.get_staged_diff", return_value="diff --git ...")
    @patch("monitor.core.commit.input")
    def test_make_commit_command_edit_flow(
        self,
        mock_input,
        mock_get_staged_diff,
        mock_get_suggested,
        mock_tmpfile,
        mock_perform_git_commit,
        mock_run,
        mock_unlink,
    ):
        """Edit flow uses edited content for commit and prints success."""
        mock_input.side_effect = ["e", "y"]
        mock_run.return_value = MagicMock(returncode=0)

        # Mock temp file creation (used directly, not as a context manager)
        mock_file = MagicMock()
        mock_file.name = "tempfile"
        mock_tmpfile.return_value = mock_file

        # Mock reading edited content
        open_cm = MagicMock()
        open_cm.__enter__.return_value.read.return_value = "Edited message"

        outputs = []

        def capprint(msg, *a, **k):
            outputs.append(str(msg))

        with patch("monitor.core.commit.open", return_value=open_cm) as mock_open:
            commit.make_commit_command(print_func=capprint)

        mock_perform_git_commit.assert_called_once_with("Edited message")
        combined_printed = "\n".join(outputs)
        assert (
            "✅ Commit created successfully" in combined_printed
        ), "Success message not printed after edit flow. Captured: %s" % outputs

    @patch("os.unlink")
    @patch("monitor.core.commit.subprocess.run")
    @patch("monitor.core.commit.perform_git_commit")
    @patch("monitor.core.commit.tempfile.NamedTemporaryFile")
    @patch("monitor.core.commit.get_suggested_commit_message", return_value="msg")
    @patch("monitor.core.commit.get_staged_diff", return_value="diff --git ...")
    @patch("monitor.core.commit.input")
    def test_make_commit_command_editor_nonzero_exit_aborts(
        self,
        mock_input,
        mock_get_staged_diff,
        mock_get_suggested,
        mock_tmpfile,
        mock_perform_git_commit,
        mock_run,
        mock_unlink,
    ):
        """A non-zero editor exit aborts the commit and still cleans up the temp file."""
        mock_input.side_effect = ["e"]
        mock_run.return_value = MagicMock(returncode=1)
        mock_file = MagicMock()
        mock_file.name = "tempfile"
        mock_tmpfile.return_value = mock_file

        outputs = []

        def capprint(msg, *a, **k):
            outputs.append(str(msg))

        commit.make_commit_command(print_func=capprint)

        mock_perform_git_commit.assert_not_called()
        mock_unlink.assert_called_once_with("tempfile")  # cleaned up despite abort
        assert any("non-zero status" in o for o in outputs), outputs

    @patch("monitor.core.commit.perform_git_commit")
    @patch("monitor.core.commit.get_suggested_commit_message", return_value="msg")
    @patch("monitor.core.commit.get_staged_diff", return_value="diff --git ...")
    @patch("monitor.core.commit.input", return_value="n")
    def test_make_commit_command_abort_no(
        self, mock_input, mock_get_staged_diff, mock_get_suggested, mock_perform_git_commit
    ):
        """Abort when user inputs 'n' and print abort message."""
        outputs = []

        def capprint(msg, *a, **k):
            outputs.append(str(msg))

        commit.make_commit_command(print_func=capprint)
        mock_perform_git_commit.assert_not_called()
        combined_printed = "\n".join(outputs)
        assert (
            "Aborting commit." in combined_printed
        ), "Abort message not printed on 'n'. Captured: %s" % outputs

    @patch("os.unlink")
    @patch("monitor.core.commit.subprocess.run")
    @patch("monitor.core.commit.perform_git_commit")
    @patch("monitor.core.commit.tempfile.NamedTemporaryFile")
    @patch("monitor.core.commit.get_suggested_commit_message", return_value="msg")
    @patch("monitor.core.commit.get_staged_diff", return_value="diff --git ...")
    @patch("monitor.core.commit.input")
    def test_make_commit_command_empty_after_edit(
        self,
        mock_input,
        mock_get_staged_diff,
        mock_get_suggested,
        mock_tmpfile,
        mock_perform_git_commit,
        mock_run,
        mock_unlink,
    ):
        """Abort when edited message is empty; no commit attempted."""
        mock_input.side_effect = ["e", "y"]
        mock_run.return_value = MagicMock(returncode=0)

        # Mock temp file creation (used directly, not as a context manager)
        mock_file = MagicMock()
        mock_file.name = "tempfile"
        mock_tmpfile.return_value = mock_file

        # Mock reading empty content after edit
        open_cm = MagicMock()
        open_cm.__enter__.return_value.read.return_value = ""

        outputs = []

        def capprint(msg, *a, **k):
            outputs.append(str(msg))

        with patch("monitor.core.commit.open", return_value=open_cm) as mock_open:
            commit.make_commit_command(print_func=capprint)

        mock_perform_git_commit.assert_not_called()
        combined_printed = "\n".join(outputs)
        assert (
            "Commit message cannot be empty. Aborting." in combined_printed
        ), "Empty message abort not printed. Captured: %s" % outputs

    @patch("monitor.core.commit.perform_git_commit", side_effect=Exception("fail"))
    @patch("monitor.core.commit.get_staged_diff", return_value="diff --git ...")
    @patch("monitor.core.commit.get_suggested_commit_message", return_value="msg")
    @patch("monitor.core.commit.input", return_value="y")
    def test_make_commit_command_commit_failure(
        self,
        mock_input,
        mock_get_suggested,
        mock_get_staged_diff,
        mock_perform_git_commit,
    ):
        """Print error on git commit failure."""
        outputs = []

        def capprint(msg, *a, **k):
            outputs.append(str(msg))

        commit.make_commit_command(print_func=capprint)
        combined_printed = "\n".join(outputs)
        assert (
            "Git commit failed:" in combined_printed
        ), "Commit failure message not printed. Captured: %s" % outputs

    @patch("monitor.core.commit.perform_git_commit")
    @patch("monitor.core.commit.get_suggested_commit_message", side_effect=RuntimeError("rate limited"))
    @patch("monitor.core.commit.get_staged_diff", return_value="diff --git ...")
    def test_make_commit_command_generation_failure_is_friendly(
        self, mock_get_staged_diff, mock_get_suggested, mock_perform_git_commit
    ):
        """A message-generation failure prints a friendly message and commits nothing."""
        outputs = []

        def capprint(msg, *a, **k):
            outputs.append(str(msg))

        commit.make_commit_command(print_func=capprint)
        mock_perform_git_commit.assert_not_called()
        combined = "\n".join(outputs)
        assert "Couldn't generate a commit message" in combined, outputs
        assert "staged changes are untouched" in combined, outputs

    @patch("monitor.core.commit.perform_git_commit")
    @patch("monitor.core.commit.get_suggested_commit_message", side_effect=KeyboardInterrupt)
    @patch("monitor.core.commit.get_staged_diff", return_value="diff --git ...")
    def test_make_commit_command_generation_cancelled_is_friendly(
        self, mock_get_staged_diff, mock_get_suggested, mock_perform_git_commit
    ):
        """Ctrl-C during generation aborts cleanly without a traceback or commit."""
        outputs = []

        def capprint(msg, *a, **k):
            outputs.append(str(msg))

        commit.make_commit_command(print_func=capprint)
        mock_perform_git_commit.assert_not_called()
        assert any("cancelled" in o.lower() for o in outputs), outputs

    @patch("monitor.core.commit.get_staged_diff", side_effect=Exception("oops"))
    def test_make_commit_command_top_level_exception(self, mock_get_staged_diff):
        """Top-level exception is caught and error is printed."""
        outputs = []

        def capprint(msg, *a, **k):
            outputs.append(str(msg))

        commit.make_commit_command(print_func=capprint)
        combined_printed = "\n".join(outputs)
        assert (
            "Error in :make_commit:" in combined_printed
        ), "Top-level error message not printed. Captured: %s" % outputs


if __name__ == "__main__":
    unittest.main()
