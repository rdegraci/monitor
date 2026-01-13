import unittest
from unittest.mock import patch, MagicMock
import os

from monitor.lib.display_output import display_query_result, highlightMarkdown, format_prompt_display


class TestDisplayOutput(unittest.TestCase):
    """Test cases for display_output module functions."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.sample_text = "Sample markdown text"
        self.sample_result = "# Test Result\nThis is a test result"

    @patch('monitor.lib.display_output.highlightMarkdown')
    def test_display_query_result_with_update_history(self, mock_highlight):
        """Test display_query_result calls highlight and update_history functions."""
        mock_update_history = MagicMock()

        display_query_result(self.sample_result, mock_update_history)

        mock_highlight.assert_called_once_with(self.sample_result)
        mock_update_history.assert_called_once()

    @patch('monitor.lib.display_output.highlightMarkdown')
    def test_display_query_result_without_update_history(self, mock_highlight):
        """Test display_query_result works without update_history callback."""
        display_query_result(self.sample_result)

        mock_highlight.assert_called_once_with(self.sample_result)

    @patch('builtins.print')
    @patch('monitor.lib.display_output.TerminalFormatter')
    @patch('monitor.lib.display_output.MarkdownLexer')
    @patch('monitor.lib.display_output.highlight')
    def test_highlightMarkdown_with_valid_input(self, mock_highlight, mock_markdown_lexer, mock_terminal_formatter, mock_print):
        """Test highlightMarkdown with valid query result."""
        lexer_instance = MagicMock(name="MarkdownLexerInstance")
        formatter_instance = MagicMock(name="TerminalFormatterInstance")
        mock_markdown_lexer.return_value = lexer_instance
        mock_terminal_formatter.return_value = formatter_instance
        mock_highlight.return_value = "highlighted_text"

        highlightMarkdown(self.sample_result)

        mock_markdown_lexer.assert_called_once_with()
        mock_terminal_formatter.assert_called_once_with(reset=True)
        mock_highlight.assert_called_once_with(self.sample_result, lexer_instance, formatter_instance)

        print_calls = [args[0] if args else "" for args, _kwargs in mock_print.call_args_list]
        self.assertTrue(any("\n" in str(c) and "STX" in str(c) for c in print_calls))
        self.assertTrue(any("ETX" in str(c) for c in print_calls))
        self.assertTrue(any("Generated:" in str(c) for c in print_calls))

    @patch('builtins.print')
    def test_highlightMarkdown_with_none_input(self, mock_print):
        """Test highlightMarkdown handles None input gracefully."""
        highlightMarkdown(None)

        print_calls = [args[0] if args else "" for args, _kwargs in mock_print.call_args_list]
        self.assertTrue(any("No query result." in str(c) for c in print_calls))

    def test_format_prompt_display_basic(self):
        """Test format_prompt_display with basic parameters."""
        result = format_prompt_display(
            conversation_count=5,
            tokens_remaining=1000,
            cwd="/test/dir",
            model="test-model"
        )

        self.assertIn("5", result)  # conversation count
        self.assertIn("1000", result)  # context remaining derived from tokens_remaining
        self.assertIn("/test/dir", result)  # cwd
        self.assertIn("test-model", result)  # model
        self.assertIn("C:", result)  # context label
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
        self.assertIn("C:", result)
        self.assertIn("H:", result)

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
        self.assertIn("C:", result)
        self.assertIn("H:", result)

    @patch('os.getcwd')
    @patch('builtins.print')
    def test_format_prompt_display_cwd_error_handling(self, mock_print, mock_getcwd):
        """Test format_prompt_display handles os.getcwd() errors gracefully."""
        mock_getcwd.side_effect = OSError("Permission denied")

        result = format_prompt_display(
            conversation_count=1,
            tokens_remaining=100
        )

        self.assertIn("Error in getting current working directory", result)
        mock_print.assert_called()

    @patch('builtins.print')
    def test_format_prompt_display_count_error_handling(self, mock_print):
        """Test format_prompt_display handles errors in count calculations."""
        result = format_prompt_display(
            conversation_count="invalid",
            tokens_remaining="also_invalid",
            cwd="/test"
        )

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

        self.assertIn("10", result)
        self.assertIn("2500", result)
        self.assertIn("/home/user/project", result)
        self.assertIn("gpt-4", result)
        self.assertIn("(modified)", result)
        self.assertIn("C:", result)
        self.assertIn("H:", result)
        self.assertIn("]", result)  # End bracket of prompt


if __name__ == "__main__":
    unittest.main()
