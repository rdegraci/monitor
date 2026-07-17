import unittest
from unittest.mock import patch, MagicMock
import monitor.core.built_ins as built_ins
import monitor.lib.built_in_commands as bic
import copy

class TestConfigureBuiltIns(unittest.TestCase):
    @patch('monitor.core.built_ins.append_function_to_built_ins')
    def test_all_registrations_called(self, mock_append):
        """
        Test that append_function_to_built_ins is called for each registration.
        """
        built_ins.configure_built_ins()
        # The minimum number of registrations is the number of commands in the function,
        # here counted by manually scanning the configure_built_ins source.
        # If more commands are added, update expected_call_count.
        expected_call_count = 30  # Update this if commands are added/removed in the future.
        self.assertGreaterEqual(mock_append.call_count, expected_call_count)

    @patch('monitor.core.built_ins.print_colored_error')
    @patch('monitor.core.built_ins.append_function_to_built_ins', side_effect=Exception('DummyError'))
    def test_error_handling_on_registration_failure(self, mock_append, mock_error):
        """
        Test that print_colored_error is called if registration fails.
        """
        built_ins.configure_built_ins()
        self.assertGreaterEqual(mock_error.call_count, 30)  # Update this if commands are added/removed in the future.
        for call in mock_error.call_args_list:
            args, kwargs = call
            self.assertTrue('Failed to register' in args[0])



if __name__ == "__main__":
    unittest.main()
