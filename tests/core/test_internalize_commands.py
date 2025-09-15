import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace


class TestInternalizeCommands(unittest.TestCase):
    """Covers src/monitor/core/internalize_commands.rip_grep_command."""

    def test_no_matches_short_circuits_and_prints_info(self):
        """If grep returns the exact sentinel string, print info and return None."""
        from monitor.core import internalize_commands as mod

        with patch.object(mod, "grep_command", return_value="No matches found."), \
            patch.object(mod, "print_colored_info") as mock_info, \
            patch.object(mod, "internalize_command") as mock_internalize:
            res = mod.rip_grep_command("foo", print_func=lambda *_: None)

        self.assertIsNone(res)
        mock_info.assert_called_once()
        # Must not call internalize_command when no matches
        mock_internalize.assert_not_called()

    def test_happy_path_calls_internalize_with_prompt(self):
        """On matches, print the raw grep result and internalize an explanation prompt."""
        from monitor.core import internalize_commands as mod

        grep_out = "file.py:1: print('foo')\nfile.py:2: foo = 1"
        captured = []

        with patch.object(mod, "grep_command", return_value=grep_out), \
            patch.object(mod, "internalize_command", return_value="OK") as mock_internalize, \
            patch.object(mod, "config", SimpleNamespace(MODEL_CONTEXT_WINDOW=None, MAX_TOKEN_COUNT=10000)):
            res = mod.rip_grep_command("foo", print_func=lambda s: captured.append(s))

        self.assertEqual(res, "OK")
        self.assertEqual(captured, [grep_out])
        # Verify the prompt was constructed with tags and includes the content
        args, kwargs = mock_internalize.call_args
        prompt = args[0]
        self.assertIn("<search_key>foo</search_key>", prompt)
        self.assertIn("<search_results>" + grep_out + "</search_results>", prompt)

    def test_truncates_when_exceeds_model_window(self):
        """When output exceeds SAFE_LIMIT, truncates and annotates the bytes removed."""
        from monitor.core import internalize_commands as mod

        with patch.object(mod, "logger") as mock_logger:
            long_text = "X" * 50  # deterministic ASCII for byte counts
            # MODEL_CONTEXT_WINDOW=100 -> SAFE_LIMIT = 10 characters
            cfg = SimpleNamespace(MODEL_CONTEXT_WINDOW=100, MAX_TOKEN_COUNT=0)
            with patch.object(mod, "grep_command", return_value=long_text), \
                patch.object(mod, "internalize_command", return_value="OK") as mock_internalize, \
                patch.object(mod, "config", cfg):
                res = mod.rip_grep_command("foo")

        self.assertEqual(res, "OK")
        # Ensure truncation occurred in the prompt sent to internalize_command
        prompt = mock_internalize.call_args[0][0]
        self.assertIn("[TRUNCATED", prompt)
        # Check logger.warning was called for truncation
        mock_logger.warning.assert_called()

    def test_uses_max_token_count_if_no_model_window(self):
        """If MODEL_CONTEXT_WINDOW is unset, falls back to MAX_TOKEN_COUNT (string convertible)."""
        from monitor.core import internalize_commands as mod

        long_text = "Y" * 30
        cfg = SimpleNamespace(MODEL_CONTEXT_WINDOW=None, MAX_TOKEN_COUNT="15")  # SAFE_LIMIT = 15
        with patch.object(mod, "grep_command", return_value=long_text), \
            patch.object(mod, "internalize_command", return_value="OK") as mock_internalize, \
            patch.object(mod, "config", cfg):
            _ = mod.rip_grep_command("bar")
        prompt = mock_internalize.call_args[0][0]
        self.assertIn("[TRUNCATED", prompt)

    def test_invalid_max_token_count_disables_truncation(self):
        """If MAX_TOKEN_COUNT cannot be coerced, SAFE_LIMIT becomes 0 and no truncation occurs."""
        from monitor.core import internalize_commands as mod

        long_text = "Z" * 100
        cfg = SimpleNamespace(MODEL_CONTEXT_WINDOW=None, MAX_TOKEN_COUNT="not-an-int")
        with patch.object(mod, "grep_command", return_value=long_text), \
            patch.object(mod, "internalize_command", return_value="OK") as mock_internalize, \
            patch.object(mod, "config", cfg):
            _ = mod.rip_grep_command("baz")
        prompt = mock_internalize.call_args[0][0]
        # Expect the full text without a TRUNCATED marker
        self.assertNotIn("[TRUNCATED", prompt)
        self.assertIn(long_text, prompt)


if __name__ == "__main__":
    unittest.main()
