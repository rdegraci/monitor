
import unittest
from unittest.mock import patch, MagicMock
import monitor.core.modes as modes

class TestModes(unittest.TestCase):
    def setUp(self):
        # Reset DESIGN_MODE_ACTIVE before each test
        modes.DESIGN_MODE_ACTIVE = False

    @patch('monitor.core.modes.DESIGN_CONSULT')
    @patch('builtins.input', side_effect=['input text', ':exit'])
    @patch('builtins.print')
    def test_design_mode_command_exit(self, mock_print, mock_input, mock_design_consult):
        mock_design_consult_instance = MagicMock()
        mock_design_consult.return_value = mock_design_consult_instance
        # Set up DESIGN_CONSULT methods
        mock_design_consult_instance.ask.return_value = ("Q?", "prompt")
        # Patch DESIGN_CONSULT singleton for direct usage
        modes.DESIGN_CONSULT = mock_design_consult_instance
        modes.design_mode_command(seed_question="What?")
        self.assertFalse(modes.DESIGN_MODE_ACTIVE)
        mock_design_consult_instance.start.assert_called_once_with(seed_question='What?')
        mock_design_consult_instance.ask.assert_called()
        mock_print.assert_any_call("Design mode activated. Begin describing your software or respond to questions.")
        mock_print.assert_any_call("Exiting design mode without entering dev mode.")
        mock_print.assert_any_call("Design mode ended.")

    @patch('monitor.core.modes.DESIGN_CONSULT')
    @patch('builtins.input', side_effect=[":dev_mode"])
    @patch('monitor.core.modes.query')
    @patch('monitor.core.modes.display_query_result')
    @patch('monitor.core.modes.send_artifact')
    @patch('builtins.print')
    def test_design_mode_to_dev_mode(self, mock_print, mock_send_artifact, mock_display, mock_query, mock_input, mock_design_consult):
        mock_design_consult_instance = MagicMock()
        mock_design_consult.return_value = mock_design_consult_instance
        # Set up DESIGN_CONSULT methods
        mock_design_consult_instance.ask.return_value = ("Q?", "prompt")
        mock_design_consult_instance.stop.return_value = "PROMPT STR"
        # Patch DESIGN_CONSULT singleton for direct usage
        modes.DESIGN_CONSULT = mock_design_consult_instance
        mock_query.return_value = "QUERY RESULT"
        modes.DESIGN_MODE_ACTIVE = False
        modes.design_mode_command()
        mock_design_consult_instance.start.assert_called_once()
        mock_design_consult_instance.stop.assert_called_once()
        mock_display.assert_called_once_with("QUERY RESULT", update_history_count=unittest.mock.ANY)
        mock_send_artifact.assert_called_once_with("QUERY RESULT")
        self.assertFalse(modes.DESIGN_MODE_ACTIVE)

    @patch('builtins.print')
    def test_dev_mode_command_not_active(self, mock_print):
        modes.DESIGN_MODE_ACTIVE = False
        modes.dev_mode_command()
        mock_print.assert_any_call("Not currently in design mode.")

    @patch('monitor.core.modes.DESIGN_CONSULT')
    @patch('monitor.core.modes.query')
    @patch('monitor.core.modes.display_query_result')
    @patch('monitor.core.modes.send_artifact')
    @patch('builtins.print')
    def test_dev_mode_command_active(self, mock_print, mock_send_artifact, mock_display, mock_query, mock_design_consult):
        modes.DESIGN_MODE_ACTIVE = True
        mock_design_consult_instance = MagicMock()
        # Patch DESIGN_CONSULT singleton for direct usage
        mock_design_consult.return_value = mock_design_consult_instance
        modes.DESIGN_CONSULT = mock_design_consult_instance
        mock_design_consult_instance.stop.return_value = "PROMPT STR"
        mock_query.return_value = "QUERY RESULT"
        modes.dev_mode_command()
        mock_design_consult_instance.stop.assert_called_once()
        mock_display.assert_called_once_with("QUERY RESULT", update_history_count=unittest.mock.ANY)
        mock_send_artifact.assert_called_once_with("QUERY RESULT")
        self.assertFalse(modes.DESIGN_MODE_ACTIVE)

if __name__ == "__main__":
    unittest.main()


