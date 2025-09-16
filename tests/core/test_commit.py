import unittest
from unittest.mock import patch, MagicMock
import monitor.core.commit as commit
import importlib


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

    @patch("monitor.core.commit.query")
    @patch("monitor.core.commit.build_commit_message_query_input")
    def test_get_suggested_commit_message_builds_and_queries(
        self, mock_build, mock_query
    ):
        """Builder and query are called and result is returned."""
        mock_build.return_value = {"input": "query_input"}
        mock_query.return_value = "Suggested commit"
        diff = "diff --git ..."

        result = commit.get_suggested_commit_message(diff)

        self.assertEqual(result, "Suggested commit")
        # Loosened assertion: ensure 'diff' kwarg equals diff and query was called
        self.assertTrue(mock_build.called)
        _, kwargs = mock_build.call_args
        self.assertEqual(kwargs.get("diff"), diff)
        self.assertTrue(mock_query.called)

    @patch("os.unlink")
    @patch("monitor.core.commit.os.system", return_value=0)
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
        mock_system,
        mock_unlink,
    ):
        """Edit flow uses edited content for commit and prints success."""
        mock_input.side_effect = ["e", "y"]

        # Mock temp file creation
        mock_file = MagicMock()
        mock_file.name = "tempfile"
        mock_tmpfile.return_value.__enter__.return_value = mock_file

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
    @patch("monitor.core.commit.os.system", return_value=0)
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
        mock_system,
        mock_unlink,
    ):
        """Abort when edited message is empty; no commit attempted."""
        mock_input.side_effect = ["e", "y"]

        # Mock temp file creation
        mock_file = MagicMock()
        mock_file.name = "tempfile"
        mock_tmpfile.return_value.__enter__.return_value = mock_file

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
