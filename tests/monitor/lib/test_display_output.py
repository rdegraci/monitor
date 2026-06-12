import contextlib
import unittest
from unittest.mock import patch, MagicMock

import monitor.lib.display_output as display_output
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

    @patch('monitor.lib.display_output.os.getcwd')
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

    @patch('monitor.lib.display_output.os.getcwd')
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

    def test_format_prompt_display_last_used_estimated_yellow(self):
        """Test format_prompt_display includes L: when last_used is available and uses yellow when estimate is True."""
        with patch.object(display_output.config, 'LAST_REQUEST_TOKEN_COUNT', 123, create=True), \
                patch.object(display_output.config, 'LAST_REQUEST_USED_ESTIMATE', True, create=True):
            result = format_prompt_display(
                conversation_count=2,
                tokens_remaining=500,
                cwd="/test",
                model="test-model"
            )

        self.assertIn("L:", result)
        self.assertIn("123", result)
        self.assertIn(display_output.yellow, result)

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

    def test_history_tokens_rendered_as_suffix_on_H(self):
        # H:<count> (<compactions>) <history_tokens>t — the retained-history
        # token size (cost-relevant baseline re-sent each request).
        with patch.object(display_output.config, "SESSION_COMPACTION_COUNT", 1):
            result = format_prompt_display(
                conversation_count=29, tokens_remaining=909916,
                context_remaining=909916, context_budget=922000,
                history_tokens=12084,
            )
        self.assertIn("H:29 (1) 12084t", result)

    def test_history_tokens_omitted_when_not_supplied(self):
        # Back-compat: no history_tokens -> bare H:<count>, no "t" suffix.
        with patch.object(display_output.config, "SESSION_COMPACTION_COUNT", 0):
            result = format_prompt_display(conversation_count=5, tokens_remaining=900000)
        self.assertIn("H:5", result)
        self.assertNotIn("t ", result.split("H:")[1] if "H:" in result else "")
        self.assertNotIn("5t", result)


class TestFuelGauge(unittest.TestCase):
    """The F: fuel tank: SESSION_TOKEN_BUDGET - SESSION_TOTAL_TOKENS, drawn
    before C: as the exact remaining token count plus percent. No price."""

    def _line(self, **over):
        # These tests pin the cap via the explicit SESSION_TOKEN_BUDGET override
        # (and DAILY_COST_TARGET_USD=0 so nothing derives), isolating the F:
        # *rendering* from the budget-derivation logic (covered separately).
        import monitor.config as config
        budget = over.pop("budget", 10_000_000)
        with patch.object(config, "SESSION_TOKEN_BUDGET", budget), \
             patch.object(config, "DAILY_COST_TARGET_USD", over.pop("cost_target", 0.0)), \
             patch.object(config, "SESSION_TOTAL_TOKENS", over.get("total_used", 0)):
            kwargs = dict(conversation_count=18, tokens_remaining=914345,
                          context_remaining=914345, context_budget=924000,
                          rate_remaining=4000000, last_used=188977, model="m")
            kwargs.update(over)
            return format_prompt_display(**kwargs)

    def test_fuel_drawn_before_context(self):
        line = self._line(total_used=4_801_805)
        self.assertIn("F:", line)
        self.assertLess(line.index("F:"), line.index("C:"))  # F: precedes C:

    def test_exact_remaining_count_and_percent(self):
        # 10M cap - 4,801,805 used -> exact 5,198,195 (51.98%), no shorthand.
        line = self._line(total_used=4_801_805)
        self.assertIn("F:5198195 (51.98%)", line)
        self.assertNotIn("5.2M", line)  # not abbreviated

    def test_no_price_shown(self):
        line = self._line(total_used=4_801_805)
        self.assertNotIn("$", line.split("C:")[0])  # nothing dollar-ish in the F: segment

    def test_full_tank_shows_clean_100(self):
        # Genuinely full (nothing used) -> "100%", no decimals.
        line = self._line(total_used=0)
        self.assertIn("F:10000000 (100%)", line)

    def test_barely_used_does_not_round_up_to_100(self):
        # 1 token used must read 99.99%, NOT 100.00% — the truncation guard.
        line = self._line(total_used=1)
        self.assertIn("F:9999999 (99.99%)", line)

    def test_overrun_goes_negative(self):
        line = self._line(total_used=10_400_000)
        self.assertIn("F:-400000 (-4.00%)", line)

    def test_no_budget_disables_gauge(self):
        # No explicit override and no dollar target -> gauge hidden.
        line = self._line(total_used=4_801_805, budget=None, cost_target=0.0)
        self.assertNotIn("F:", line)
        self.assertIn("C:", line)  # rest of the line intact


class TestFuelBudgetDerivation(unittest.TestCase):
    """The dollar-target-derived F: cap: DAILY_COST_TARGET_USD / per-model rate,
    auto-scaling across models and reasoning effort (session_token_budget)."""

    def _budget(self, model="openai/gpt-5.4", effort="medium", **cfg):
        import monitor.config as config
        from monitor.lib.model_pricing import session_token_budget
        settings = dict(
            SESSION_TOKEN_BUDGET=None,
            DAILY_COST_TARGET_USD=5.0,
            MODEL_TOKEN_RATE_PER_MTOK={"openai/gpt-5.4": 1.0},
            TOKEN_RATE_ANCHOR_MODEL="openai/gpt-5.4",
            DEFAULT_TOKEN_RATE_PER_MTOK=1.0,
            REASONING_EFFORT_RATE_MULTIPLIER={"minimal": 0.5, "low": 0.75, "medium": 1.0, "high": 1.75},
            MODEL=model,
            REASONING_MODEL_PREFIX="gpt-5",
            REASONING_EFFORT=effort,
            MODEL_PRICING_OVERRIDES={},
        )
        settings.update(cfg)
        with contextlib.ExitStack() as stack:
            for k, v in settings.items():
                stack.enter_context(patch.object(config, k, v, create=True))
            return session_token_budget()

    def test_anchor_model_medium_hits_target(self):
        # $5 / $1.00 per M = 5M tokens.
        self.assertEqual(self._budget("openai/gpt-5.4", "medium"), 5_000_000)

    def test_cheaper_model_yields_bigger_tank(self):
        # gpt-5.4-mini is ~1/8 the price -> ~39M for the same $5/day.
        b = self._budget("openai/gpt-5.4-mini", "medium")
        self.assertGreater(b, 30_000_000)
        self.assertLess(b, 50_000_000)

    def test_pricier_model_yields_smaller_tank(self):
        # opus-4-7 ~1.7x -> ~2.9M.
        b = self._budget("anthropic/claude-opus-4-7", "medium")
        self.assertGreater(b, 2_000_000)
        self.assertLess(b, 3_500_000)

    def test_higher_effort_shrinks_tank(self):
        low = self._budget("openai/gpt-5.4", "low")
        med = self._budget("openai/gpt-5.4", "medium")
        high = self._budget("openai/gpt-5.4", "high")
        self.assertGreater(low, med)
        self.assertLess(high, med)
        self.assertEqual(high, int(5.0 / (1.75 / 1_000_000)))  # exact: ~2.857M

    def test_effort_ignored_for_non_reasoning_model(self):
        # prefix absent from model name -> multiplier 1.0 whatever the effort.
        b = self._budget("openai/gpt-5.4", "high", REASONING_MODEL_PREFIX="zzz")
        self.assertEqual(b, 5_000_000)

    def test_explicit_override_wins(self):
        self.assertEqual(
            self._budget("openai/gpt-5.4", "high", SESSION_TOKEN_BUDGET=7_000_000),
            7_000_000,
        )

    def test_zero_target_disables(self):
        self.assertIsNone(self._budget("openai/gpt-5.4", "medium", DAILY_COST_TARGET_USD=0))


if __name__ == "__main__":
    unittest.main()
