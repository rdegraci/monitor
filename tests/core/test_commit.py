
import unittest
from unittest.mock import patch, MagicMock
import monitor.core.commit as commit
import importlib
import pprint

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
        mock_unlink
    ):
        """Test successful make_commit_command flow with all happy paths mocked."""
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

        with patch("builtins.print") as mock_print:
            commit.make_commit_command()
            # Print the mock_print call args list for precise diagnostic information
            pprint.pprint(mock_print.call_args_list)
            printed_strs = [call[0][0] for call in mock_print.call_args_list if call[0]]
            mock_perform_git_commit.assert_called_once_with("Add new feature")
            # Assert the commit success message is present in any print call
            assert any("✅ Commit created successfully" in s for s in printed_strs), \
                "The commit success message was not printed. Calls captured: %s" % printed_strs

    @patch("monitor.core.commit.get_staged_diff", return_value="")
    def test_make_commit_command_no_staged_changes(self, mock_get_staged_diff):
        """Test make_commit_command with no staged changes."""
        colors = importlib.import_module("monitor.lib.colors")
        yellow = getattr(colors, "yellow")
        reset = getattr(colors, "reset")

        with patch("builtins.print") as mock_print:
            commit.make_commit_command()
            # Print the mock_print call args list for precise diagnostic information
            pprint.pprint(mock_print.call_args_list)
            printed_strs = [call[0][0] for call in mock_print.call_args_list if call[0]]
            # Assert the 'no staged changes' message is present in any print call
            assert any("No staged changes to commit. Please stage changes first." in s for s in printed_strs), \
                "The 'no staged changes' message was not printed. Calls captured: %s" % printed_strs

if __name__ == "__main__":
    unittest.main()


