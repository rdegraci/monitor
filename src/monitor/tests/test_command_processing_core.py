import unittest
from unittest.mock import patch, MagicMock

import monitor.core.command_processing as command_processing

class TestCommandProcessing(unittest.TestCase):
    @patch("core.command_processing.handle_cd_command", return_value="/mock/dir")
    @patch("core.command_processing.query")
    def test_process_cd_command(self, mock_query, mock_handle_cd):
        # Should process and invoke CD handling for 'cd' command
        result = command_processing.process_cd_command("cd mydir", "cd")
        self.assertTrue(result)
        mock_handle_cd.assert_called_once_with("mydir")
        mock_query.assert_called_once()

        # Should not process for a non-cd command
        result2 = command_processing.process_cd_command("ls -l", "ls")
        self.assertFalse(result2)

    def test_handle_exit_command(self):
        with patch("signal.signal") as mock_signal, patch("builtins.print"):
            self.assertTrue(command_processing.handle_exit_command("/exit"))
            self.assertTrue(command_processing.handle_exit_command("exit"))
            self.assertFalse(command_processing.handle_exit_command("foo"))
            mock_signal.assert_called()

    @patch("core.command_processing.readline.write_history_file")
    @patch("core.command_processing.process_macro_command", return_value=False)
    @patch("core.command_processing.handle_exit_command", return_value=False)
    @patch("core.command_processing.process_cd_command", return_value=False)
    @patch("core.command_processing.is_interactive_command", return_value=False)
    @patch("core.command_processing.is_internal_command", return_value=False)
    @patch("core.command_processing.is_built_in_function", return_value=False)
    @patch("core.command_processing.query", return_value="query_result")
    @patch("core.command_processing.send_artifact")
    @patch("core.command_processing.display_query_result")
    def test_process_command_query(
        self,
        mock_display,
        mock_send_artifact,
        mock_query,
        mock_is_built_in,
        mock_is_internal,
        mock_is_interactive,
        mock_process_cd,
        mock_handle_exit,
        mock_process_macro,
        mock_history,
    ):
        # Should process as a general query command
        should_exit = command_processing.process_command("whoami", "/tmp/f")
        self.assertFalse(should_exit)
        mock_history.assert_called_once()
        mock_display.assert_called()

    @patch("core.command_processing.process_macro_command", return_value=True)
    def test_process_command_macro(self, mock_proc_macro):
        # Macro detected, so returns early
        res = command_processing.process_command("<(macro);", "/tmp/f")
        self.assertFalse(res)

    @patch("core.command_processing.handle_exit_command", return_value=True)
    def test_process_command_exit(self, mock_handle_exit):
        # Exit command triggers exit
        res = command_processing.process_command("exit", "/tmp/f")
        self.assertTrue(res)

if __name__ == "__main__":
    unittest.main()
