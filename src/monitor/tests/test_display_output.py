import unittest
from unittest.mock import patch, MagicMock, call
import os
import sys

# Add the parent directory to the path to import the module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor.lib.display_output import display_query_result, highlightMarkdown, format_prompt_display


class TestDisplayOutput(unittest.TestCase):
    """Test cases for display_output module functions."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.sample_text = "Sample markdown text"
        self.sample_result = "# Test Result\nThis is a test result"

    @patch('lib.display_output.highlightMarkdown')
    def test_display_query_result_with_update_history(self, mock_highlight):
        """Test display_query_result calls highlight and update_history functions."""
        mock_update_history = MagicMock()
        
        display_query_result(self.sample_result, mock_update_history)
        
        mock_highlight.assert_called_once_with(self.sample_result)
        mock_update_history.assert_called_once()

    @patch('lib.display_output.highlightMarkdown')
    def test_display_query_result_without_update_history(self, mock_highlight):
        """Test display_query_result works without update_history callback."""
        display_query_result(self.sample_result)
        
        mock_highlight.assert_called_once_with(self.sample_result)

    @patch('builtins.print')
    @patch('lib.display_output.highlight')
    def test_highlightMarkdown_with_valid_input(self, mock_highlight, mock_print):
        """Test highlightMarkdown with valid query result."""
        mock_highlight.return_value = "highlighted_text"
        
        highlightMarkdown(self.sample_result)
        
        # Verify highlight was called with correct parameters
        mock_highlight.assert_called_once()
        # Verify print statements include expected content
        print_calls = mock_print.call_args_list
        self.assertTrue(any("STX" in str(call) for call in print_calls))
        self.assertTrue(any("ETX" in str(call) for call in print_calls))
        self.assertTrue(any("*******************" in str(call) for call in print_calls))

    @patch('builtins.print')
    def test_highlightMarkdown_with_none_input(self, mock_print):
        """Test highlightMarkdown handles None input gracefully."""
        highlightMarkdown(None)
        
        # Should print "No query result" message
        print_calls = mock_print.call_args_list
        self.assertTrue(any("No query result" in str(call) for call in print_calls))

    def test_format_prompt_display_basic(self):
        """Test format_prompt_display with basic parameters."""
        result = format_prompt_display(
            conversation_count=5,
            tokens_remaining=1000,
            cwd="/test/dir",
            model="test-model"
        )
        
        self.assertIn("5", result)  # conversation count
        self.assertIn("1000", result)  # tokens remaining
        self.assertIn("/test/dir", result)  # cwd
        self.assertIn("test-model", result)  # model
        self.assertIn("T:", result)  # tokens label
        self.assertIn("H:", result)  # history label

    def test_format_prompt_display_zero_tokens(self):
        """Test format_prompt_display handles zero tokens (should use red color)."""
        result = format_prompt_display(
            conversation_count=3,
            tokens_remaining=0,
            cwd="/test",
            model="test-model"
        )
        
        self.assertIn("0", result)
        self.assertIn("3", result)

    @patch('os.getcwd')
    def test_format_prompt_display_auto_cwd(self, mock_getcwd):
        """Test format_prompt_display automatically gets current directory when cwd is None."""
        mock_getcwd.return_value = "/auto/detected/dir"
        
        result = format_prompt_display(
            conversation_count=2,
            tokens_remaining=500
        )
        
        mock_getcwd.assert_called_once()
        self.assertIn("/auto/detected/dir", result)

    def test_format_prompt_display_with_extra_history(self):
        """Test format_prompt_display includes extra history string."""
        extra_str = " (cached)"
        result = format_prompt_display(
            conversation_count=4,
            tokens_remaining=750,
            cwd="/test",
            extra_history_str=extra_str
        )
        
        self.assertIn(extra_str, result)

    def test_format_prompt_display_no_model(self):
        """Test format_prompt_display works without model parameter."""
        result = format_prompt_display(
            conversation_count=1,
            tokens_remaining=100,
            cwd="/test"
        )
        
        self.assertIn("1", result)
        self.assertIn("100", result)
        self.assertIn("/test", result)

    @patch('os.getcwd')
    @patch('builtins.print')
    def test_format_prompt_display_cwd_error_handling(self, mock_print, mock_getcwd):
        """Test format_prompt_display handles os.getcwd() errors gracefully."""
        mock_getcwd.side_effect = OSError("Permission denied")
        
        result = format_prompt_display(
            conversation_count=1,
            tokens_remaining=100
        )
        
        # Should handle the error and include error message
        self.assertIn("Error in getting current working directory", result)
        # Should print error message
        mock_print.assert_called()

    @patch('builtins.print')
    def test_format_prompt_display_count_error_handling(self, mock_print):
        """Test format_prompt_display handles errors in count calculations."""
        # Test with invalid conversation_count that might cause issues
        # Note: In practice, these should be integers, but testing error handling
        result = format_prompt_display(
            conversation_count="invalid",
            tokens_remaining="also_invalid",
            cwd="/test"
        )
        
        # Function should still return a result even with errors
        self.assertIsInstance(result, str)
        self.assertIn("/test", result)

    def test_format_prompt_display_complete_example(self):
        """Test format_prompt_display with all parameters provided."""
        result = format_prompt_display(
            conversation_count=10,
            tokens_remaining=2500,
            cwd="/home/user/project",
            model="gpt-4",
            extra_history_str=" (modified)"
        )
        
        # Verify all components are present
        self.assertIn("10", result)
        self.assertIn("2500", result)
        self.assertIn("/home/user/project", result)
        self.assertIn("gpt-4", result)
        self.assertIn("(modified)", result)
        self.assertIn("T:", result)
        self.assertIn("H:", result)
        self.assertIn("]", result)  # End bracket of prompt


if __name__ == "__main__":
    unittest.main()