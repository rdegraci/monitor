import pytest
import unittest
from unittest import mock
from unittest.mock import patch, MagicMock
import io
import copy

import monitor.core.built_ins as built_ins
import monitor.lib.built_in_commands as bic

class TestConfigureBuiltIns(unittest.TestCase):
    @patch('monitor.lib.built_in_commands.print_colored_error')
    @patch('monitor.lib.built_in_commands.config', autospec=True)
    @patch('monitor.core.built_ins.logger', autospec=True)
    def test_trim_history_valid_number(self, mock_logger, mock_config, mock_error):
        mock_history = [f"item{i}" for i in range(10)]
        mock_config.CONVERSATION_HISTORY = mock_history
        output_msgs = []
        def fake_print(msg, *a, **kw):
            output_msgs.append(msg)
        with patch('builtins.print', fake_print):
            built_ins.trim_history_command("3")
        # After trimming, 7 items should remain
        self.assertEqual(len(mock_config.CONVERSATION_HISTORY), 7)
        # The print output should match the exact expected string
        self.assertEqual(output_msgs[-1], "Removed last 3 item(s) from conversation history.")
        mock_error.assert_not_called()

    @patch('monitor.lib.built_in_commands.print_colored_error')
    @patch('monitor.lib.built_in_commands.config', autospec=True)
    @patch('monitor.core.built_ins.logger', autospec=True)
    def test_trim_history_more_than_available(self, mock_logger, mock_config, mock_error):
        mock_history = [f"item{i}" for i in range(2)]
        mock_config.CONVERSATION_HISTORY = mock_history
        output_msgs = []
        def fake_print(msg, *a, **kw):
            output_msgs.append(msg)
        with patch('builtins.print', fake_print):
            built_ins.trim_history_command("10")
        # All items should be removed (history becomes empty)
        self.assertEqual(len(mock_config.CONVERSATION_HISTORY), 0)
        # Output should confirm that all were removed (precise matching)
        self.assertEqual(output_msgs[-1], "History contained 2 items. All were removed.")
        mock_error.assert_not_called()

    @patch('monitor.lib.built_in_commands.print_colored_error')
    @patch('monitor.lib.built_in_commands.config', autospec=True)
    @patch('monitor.core.built_ins.logger', autospec=True)
    def test_trim_history_zero_or_negative(self, mock_logger, mock_config, mock_error):
        mock_config.CONVERSATION_HISTORY = [1,2,3]
        built_ins.trim_history_command("0")
        built_ins.trim_history_command("-5")
        # Test both responses, which should both call error handler with correct string
        # Single-argument error handler is always called with the error message as the first
        # element in args tuple, so index with [0] for clarity and robustness.
        mock_error.assert_any_call("Number of items to remove must be positive.")
        mock_error.assert_any_call("Number of items to remove must be positive.")
        self.assertGreaterEqual(mock_error.call_count, 2)


    @patch('monitor.lib.built_in_commands.print_colored_error')
    @patch('monitor.lib.built_in_commands.config', autospec=True)
    @patch('monitor.core.built_ins.logger', autospec=True)
    def test_trim_history_non_integer(self, mock_logger, mock_config, mock_error):
        mock_config.CONVERSATION_HISTORY = [1,2,3]
        built_ins.trim_history_command("ten")
        mock_error.assert_any_call("Cannot parse number of items to remove from history: 'ten'")
        built_ins.trim_history_command("3.14")
        mock_error.assert_any_call("Cannot parse number of items to remove from history: '3.14'")
        self.assertGreaterEqual(mock_error.call_count, 2)
        # In the single-argument handler scenario, call_arg is a tuple whose first position contains the error string.
        # This is now respected everywhere these arguments are accessed, for clarity and robustness.
        args0, _ = mock_error.call_args_list[0]
        self.assertIn("Cannot parse number of items", args0[0])


    @patch('monitor.lib.built_in_commands.print_colored_error')
    @patch('monitor.lib.built_in_commands.config', autospec=True)
    @patch('monitor.core.built_ins.logger', autospec=True)
    def test_trim_history_missing_or_blank_arg(self, mock_logger, mock_config, mock_error):
        mock_config.CONVERSATION_HISTORY = [1,2,3]
        built_ins.trim_history_command("")
        built_ins.trim_history_command(None)
        self.assertGreaterEqual(mock_error.call_count, 2)
        for call in mock_error.call_args_list:
            # call[0] is the tuple of positional arguments (here, the first position is the string).
            self.assertIn("You must provide a count for how many history items to remove.", call[0][0])


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

        # Find the :edit_macros registration
        found = [d for d in registrations if d.get("command") == ":edit_macros"]
        self.assertEqual(len(found), 1, "Should register :edit_macros exactly once")
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

        # Find the :reload_macros registration
        found = [r for r in registrations if r.get("command") == ":reload_macros"]
        self.assertEqual(len(found), 1, "Should register :reload_macros exactly once")
        reload_reg = found[0]
        reload_func = reload_reg["function"]

        # Call the registered function
        reload_func("test")
        mock_reload.assert_called_once_with("test")
