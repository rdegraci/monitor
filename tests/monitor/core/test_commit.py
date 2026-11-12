import importlib
import unittest
from unittest.mock import MagicMock, patch

import monitor.core.commit as commit


class TestCommitMessageFormatting(unittest.TestCase):
    def test_format_commit_body_wraps_long_prose_line(self):
        """Wraps a long prose line to the configured body limit."""
        body = (
            "This is a long prose line containing enough separate words to require "
            "wrapping at the configured commit body line length."
        )

        formatted = commit.format_commit_body(body)

        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in formatted.splitlines()
            )
        )
        self.assertEqual(
            " ".join(formatted.split()),
            " ".join(body.split()),
        )

    def test_format_commit_body_preserves_blank_lines(self):
        """Preserves blank lines while formatting the body."""
        body = (
            "First paragraph contains several words.\n"
            "\n"
            "Second paragraph contains several more words."
        )

        formatted = commit.format_commit_body(body)

        self.assertEqual(formatted.count("\n\n"), 1)
        self.assertEqual(formatted.splitlines()[1], "")

    def test_format_commit_body_reflows_wrapped_source_lines(self):
        """Keeps a paragraph's words together when the source already wraps it."""
        body = (
            "Add coverage for wrapping, blank-line preservation, URL handling,\n"
            "and long unbroken tokens."
        )

        formatted = commit.format_commit_body(body)

        self.assertEqual(" ".join(formatted.split()), " ".join(body.split()))
        self.assertIn(
            "URL handling, and long unbroken tokens.",
            " ".join(formatted.split()),
        )

    def test_format_commit_body_preserves_long_url_line(self):
        """Preserves a long line containing a URL."""
        long_url = "https://example.com/" + ("a" * 100)
        body = f"See the full documentation here:\n{long_url}"

        formatted = commit.format_commit_body(body)

        self.assertEqual(formatted, body)

    def test_format_commit_message_preserves_subject_and_formats_body(self):
        """Preserves the subject and formats a long body."""
        subject = "Add feature"
        body = (
            "This is a long prose line containing enough separate words to require "
            "wrapping at the configured commit body line length."
        )
        message = f"{subject}\n\n{body}"

        formatted = commit.format_commit_message(message)

        self.assertTrue(formatted.startswith(f"{subject}\n\n"))
        formatted_body = formatted.split("\n\n", 1)[1]
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in formatted_body.splitlines()
            )
        )
        self.assertEqual(
            " ".join(formatted_body.split()),
            " ".join(body.split()),
        )

    def test_format_commit_body_splits_long_unbroken_non_url_token(self):
        """Splits an unavoidable long non-URL token to honor the line limit."""
        long_token = "x" * (commit.COMMIT_BODY_MAX_LINE_LENGTH + 1)
        body = f"Keep this token intact: {long_token}"

        formatted = commit.format_commit_body(body)

        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in formatted.splitlines()
            )
        )
        self.assertEqual("".join(formatted.split()), "".join(body.split()))

    def test_format_commit_body_preserves_indented_lines(self):
        """Preserves indented structure lines without merging them into prose."""
        indented = "    continuation that should keep its leading spaces"
        body = (
            "Intro prose stays wrap-eligible and should still reflow normally.\n"
            "\n"
            f"{indented}\n"
            "    second indented line stays separate\n"
            "\n"
            "Outro prose after the indented block wraps independently."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        self.assertIn(indented, lines)
        self.assertIn("    second indented line stays separate", lines)
        self.assertEqual(formatted.count("\n\n"), 2)
        prose_sections = [section for section in formatted.split("\n\n") if section.strip()]
        self.assertEqual(len(prose_sections), 3)
        for section in (prose_sections[0], prose_sections[2]):
            self.assertTrue(
                all(
                    len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                    for line in section.splitlines()
                )
            )

    def test_format_commit_body_preserves_list_items(self):
        """Preserves list markers as separate structural lines (may exceed 72)."""
        long_item = (
            "- a very long list item that would wrap if merged with neighbors "
            "and still stays on its own structural line"
        )
        body = (
            "Changes include:\n"
            f"{long_item}\n"
            "* second bullet stays distinct\n"
            "+ plus bullet stays distinct\n"
            "1. numbered item stays distinct\n"
            "\n"
            "Closing prose remains wrap-eligible after the list."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        self.assertIn(long_item, lines)
        self.assertIn("* second bullet stays distinct", lines)
        self.assertIn("+ plus bullet stays distinct", lines)
        self.assertIn("1. numbered item stays distinct", lines)
        self.assertNotIn("- a very long list item that would wrap if merged with neighbors and still stays on its own structural line * second bullet", formatted)
        self.assertEqual(formatted.count("\n\n"), 1)
        closing = formatted.split("\n\n", 1)[1]
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in closing.splitlines()
            )
        )

    def test_format_commit_body_preserves_code_like_text(self):
        """Preserves fenced and indented code without reflowing into prose."""
        body = (
            "Before the sample, explain the change with enough words to wrap.\n"
            "```\n"
            "def example():\n"
            "    return 1\n"
            "```\n"
            "    indented_code = True\n"
            "\n"
            "After the sample, more prose that should still wrap normally."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        fence_start = lines.index("```")
        self.assertEqual(lines[fence_start : fence_start + 4], [
            "```",
            "def example():",
            "    return 1",
            "```",
        ])
        self.assertIn("    indented_code = True", lines)
        self.assertEqual(formatted.count("\n\n"), 1)
        before, after = formatted.split("\n\n", 1)
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in before.splitlines()
                if not line.startswith("```")
                and not line.startswith(" ")
                and not line.startswith("def ")
            )
        )
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in after.splitlines()
            )
        )

    def test_format_commit_body_preserves_tilde_fenced_code(self):
        """Preserves tilde fences as code-like structure, not reflowed prose."""
        body = (
            "Before the tilde sample, explain the change with enough words to wrap.\n"
            "~~~\n"
            "def example():\n"
            "    return 2\n"
            "~~~\n"
            "After the tilde sample, trailing prose must still wrap past the "
            "seventy-two character commit body line length limit."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        fence_start = lines.index("~~~")
        self.assertEqual(
            lines[fence_start : fence_start + 4],
            ["~~~", "def example():", "    return 2", "~~~"],
        )
        trailing = "\n".join(lines[fence_start + 4 :])
        self.assertTrue(len(trailing.splitlines()) >= 2)
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in trailing.splitlines()
            )
        )
        self.assertNotIn("~~~ def example():", formatted)

    def test_format_commit_body_does_not_close_fence_with_other_marker(self):
        """Keeps a backtick fence open when a tilde line appears inside it."""
        body = (
            "Before documenting mixed fences with enough words to wrap.\n"
            "```\n"
            "~~~\n"
            "still_inside = True\n"
            "```\n"
            "After the mixed sample, trailing prose must still wrap past the "
            "seventy-two character commit body line length limit."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        fence_start = lines.index("```")
        self.assertEqual(
            lines[fence_start : fence_start + 4],
            ["```", "~~~", "still_inside = True", "```"],
        )
        trailing = "\n".join(lines[fence_start + 4 :])
        self.assertTrue(len(trailing.splitlines()) >= 2)
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in trailing.splitlines()
            )
        )

    def test_format_commit_body_handles_long_unbreakable_tokens_in_context(self):
        """Splits long non-URL tokens in prose while leaving URL lines intact."""
        long_token = "x" * (commit.COMMIT_BODY_MAX_LINE_LENGTH + 1)
        long_url = "https://example.com/" + ("b" * 100)
        body = (
            f"See {long_token} after the token in the same sentence.\n"
            f"{long_url}\n"
            f"Then another sentence with {long_token} nearby."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        self.assertIn(long_url, lines)
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in lines
                if line != long_url
            )
        )
        self.assertEqual(
            "".join(formatted.replace(long_url, "").split()),
            "".join(body.replace(long_url, "").split()),
        )

    def test_format_commit_body_preserves_url_even_when_token_is_long(self):
        """Leaves a long URL-only line unsplit even when over the width limit."""
        long_url = "https://example.com/" + ("c" * (commit.COMMIT_BODY_MAX_LINE_LENGTH + 20))
        body = long_url

        formatted = commit.format_commit_body(body)

        self.assertEqual(formatted, body)

    def test_format_commit_body_trailing_whitespace_does_not_damage_structure(self):
        """Keeps paragraph breaks and URL exemption when trailing whitespace exists."""
        long_url = "https://example.com/docs"
        whitespace_only = "   "
        body = (
            "Para one with trailing spaces.  \n"
            "\n"
            "Para two follows a blank separator.\n"
            f"{whitespace_only}\n"
            "Para three after a whitespace-only separator.\n"
            f"{long_url}   \n"
            "Final prose after the URL line."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        self.assertGreaterEqual(formatted.count("\n\n"), 1)
        self.assertIn(whitespace_only, lines)
        self.assertIn(f"{long_url}   ", lines)
        self.assertEqual(
            " ".join(part for part in formatted.split() if not part.startswith("http")),
            " ".join(part for part in body.split() if not part.startswith("http")),
        )

    def test_format_commit_body_mixed_structure_preserves_paragraphs_and_urls(self):
        """Preserves mixed structure, URLs, and wrap-eligible prose together."""
        long_url = "https://example.com/" + ("d" * 80)
        body = (
            "Short intro prose that remains wrap-eligible.\n"
            "\n"
            "- first bullet stays structural\n"
            "* second bullet stays structural\n"
            "\n"
            "```\n"
            "code_line = 1\n"
            "```\n"
            "    indented remnant\n"
            "\n"
            f"{long_url}\n"
            "\n"
            "Trailing prose after structured content still wraps when long enough "
            "to exceed the configured commit body line length limit."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        self.assertIn("- first bullet stays structural", lines)
        self.assertIn("* second bullet stays structural", lines)
        self.assertIn("```", lines)
        self.assertIn("code_line = 1", lines)
        self.assertIn("    indented remnant", lines)
        self.assertIn(long_url, lines)
        self.assertGreaterEqual(formatted.count("\n\n"), 3)
        trailing = formatted.rsplit("\n\n", 1)[-1]
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in trailing.splitlines()
            )
        )

    def test_format_commit_body_does_not_treat_year_as_list_item(self):
        """Wraps prose that starts with a four-digit year, not a list marker."""
        body = (
            "2024. was a year of many features that need wrapping across the "
            "seventy-two character limit for commit message bodies today."
        )

        formatted = commit.format_commit_body(body)

        self.assertFalse(commit._is_list_item_line(body))
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in formatted.splitlines()
            )
        )
        self.assertEqual(" ".join(formatted.split()), " ".join(body.split()))

    def test_format_commit_body_ignores_info_string_inside_fence(self):
        """Keeps fence open when an inner line starts with backticks plus info."""
        body = (
            "Before the sample.\n"
            "```\n"
            "```inner\n"
            "still_code = True\n"
            "```\n"
            "After prose that is long enough to need wrapping past the "
            "seventy-two character commit body limit for this regression."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        fence_start = lines.index("```")
        self.assertEqual(
            lines[fence_start : fence_start + 4],
            ["```", "```inner", "still_code = True", "```"],
        )
        trailing = "\n".join(lines[fence_start + 4 :])
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in trailing.splitlines()
            )
        )
        self.assertEqual(
            " ".join(trailing.split()),
            "After prose that is long enough to need wrapping past the "
            "seventy-two character commit body limit for this regression.",
        )

    def test_format_commit_body_closing_fence_must_match_open_length(self):
        """Keeps a longer outer fence open when a shorter inner fence appears."""
        body = (
            "Example of documenting a fence with enough intro words to wrap.\n"
            "````\n"
            "```python\n"
            "print(1)\n"
            "```\n"
            "````\n"
            "After documenting the sample, this trailing prose must still wrap "
            "past the seventy-two character commit body line length limit."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        fence_start = lines.index("````")
        self.assertEqual(
            lines[fence_start : fence_start + 5],
            ["````", "```python", "print(1)", "```", "````"],
        )
        trailing = "\n".join(lines[fence_start + 5 :])
        self.assertTrue(len(trailing.splitlines()) >= 2)
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in trailing.splitlines()
            )
        )
        self.assertEqual(
            " ".join(trailing.split()),
            "After documenting the sample, this trailing prose must still wrap "
            "past the seventy-two character commit body line length limit.",
        )

    def test_format_commit_body_allows_longer_closing_fence(self):
        """Closes a fence when the closer has at least as many backticks."""
        body = (
            "Before the sample with enough words here.\n"
            "```\n"
            "code\n"
            "````\n"
            "After prose that is long enough to need wrapping past the "
            "seventy-two character commit body limit for this check."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        fence_start = lines.index("```")
        self.assertEqual(
            lines[fence_start : fence_start + 3],
            ["```", "code", "````"],
        )
        trailing = "\n".join(lines[fence_start + 3 :])
        self.assertTrue(len(trailing.splitlines()) >= 2)
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in trailing.splitlines()
            )
        )

    def test_format_commit_body_indented_fence_markers_do_not_trap_prose(self):
        """Does not toggle fence state from 4-space-indented backtick lines."""
        body = (
            "Intro prose.\n"
            "    ```\n"
            "Outro prose that is long enough that wrapping should occur for "
            "this sentence past seventy two characters in the body."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        self.assertIn("    ```", lines)
        outro = "\n".join(line for line in lines if not line.startswith(" "))
        # Drop the short intro line; remaining outro prose must wrap.
        outro_lines = [line for line in outro.splitlines() if line != "Intro prose."]
        self.assertTrue(len(outro_lines) >= 2)
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in outro_lines
            )
        )

    def test_format_commit_body_allows_fence_with_up_to_three_leading_spaces(self):
        """Treats fences with ≤3 leading spaces as real delimiters, not indent."""
        body = (
            "Before the lightly indented fence with enough words to wrap.\n"
            "  ```\n"
            "inside_fence = True\n"
            "  ```\n"
            "After the fence, trailing prose must still wrap past the "
            "seventy-two character commit body line length limit."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        fence_start = lines.index("  ```")
        self.assertEqual(
            lines[fence_start : fence_start + 3],
            ["  ```", "inside_fence = True", "  ```"],
        )
        trailing = "\n".join(lines[fence_start + 3 :])
        self.assertTrue(len(trailing.splitlines()) >= 2)
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in trailing.splitlines()
            )
        )
        self.assertEqual(
            " ".join(trailing.split()),
            "After the fence, trailing prose must still wrap past the "
            "seventy-two character commit body line length limit.",
        )

    def test_format_commit_body_preserves_language_fence_and_trailing_close(self):
        """Preserves info-string opens and whitespace-tolerant fence closes."""
        body = (
            "Explain the sample with enough words that wrapping still applies.\n"
            "```python\n"
            "value = 1\n"
            "```   \n"
            "Closing prose after the fence remains wrap-eligible and long "
            "enough to exceed the seventy-two character commit body limit."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        fence_start = lines.index("```python")
        self.assertEqual(
            lines[fence_start : fence_start + 3],
            ["```python", "value = 1", "```   "],
        )
        trailing = "\n".join(lines[fence_start + 3 :])
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in trailing.splitlines()
            )
        )

    def test_format_commit_body_preserves_tab_indented_lines(self):
        """Preserves tab-indented structure the same as space indentation."""
        tab_line = "\tcontinuation keeps its leading tab"
        body = (
            "Intro prose stays wrap-eligible around the tabbed structure.\n"
            f"{tab_line}\n"
            "Outro prose that is long enough to require wrapping past the "
            "seventy-two character commit body line length limit."
        )

        formatted = commit.format_commit_body(body)
        lines = formatted.splitlines()

        self.assertIn(tab_line, lines)
        outro = "\n".join(line for line in lines if not line.startswith("\t"))
        outro_lines = [
            line for line in outro.splitlines()
            if line != "Intro prose stays wrap-eligible around the tabbed structure."
        ]
        self.assertTrue(len(outro_lines) >= 2)
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in outro_lines
            )
        )

    def test_format_commit_message_preserves_subject_with_structured_body(self):
        """Preserves subject while keeping list and URL structure in the body."""
        subject = "Add coverage"
        long_url = "https://example.com/" + ("e" * 80)
        body = (
            "Summary prose that is long enough to wrap across the commit body "
            "line length while surrounding structured content.\n"
            "- bullet stays structural\n"
            f"{long_url}\n"
            "Trailing prose after the URL remains wrap-eligible as well."
        )
        message = f"{subject}\n\n{body}"

        formatted = commit.format_commit_message(message)

        self.assertTrue(formatted.startswith(f"{subject}\n\n"))
        formatted_body = formatted.split("\n\n", 1)[1]
        body_lines = formatted_body.splitlines()
        self.assertIn("- bullet stays structural", body_lines)
        self.assertIn(long_url, body_lines)
        prose_lines = [
            line for line in body_lines
            if line != long_url and not line.startswith("- ")
        ]
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in prose_lines
            )
        )


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

    @patch("monitor.core.commit.call_litellm_completion")
    @patch("monitor.core.commit.build_commit_message_query_input")
    def test_get_suggested_commit_message_builds_and_completes(
        self, mock_build, mock_completion
    ):
        """Builder is called and the stateless completion result is returned."""
        mock_build.return_value = "query_input"
        message = MagicMock()
        message.content = "Suggested commit"
        mock_completion.return_value.choices = [MagicMock(message=message)]
        diff = "diff --git ..."

        result = commit.get_suggested_commit_message(diff)

        self.assertEqual(result, "Suggested commit")
        self.assertTrue(mock_build.called)
        _, kwargs = mock_build.call_args
        self.assertEqual(kwargs.get("diff"), diff)
        # Uses a stateless completion, not the history-mutating query().
        self.assertFalse(hasattr(commit, "query"))
        self.assertTrue(mock_completion.called)

    @patch("monitor.core.commit.call_litellm_completion")
    @patch("monitor.core.commit.build_commit_message_query_input")
    def test_get_suggested_commit_message_wraps_long_body(
        self, mock_build, mock_completion
    ):
        """Wraps a generated commit message body to the configured line limit."""
        mock_build.return_value = "query_input"
        body = (
            "This generated commit message body contains enough separate words "
            "to require wrapping at the configured commit body line length."
        )
        message = MagicMock()
        message.content = f"Suggested commit\n\n{body}"
        mock_completion.return_value.choices = [MagicMock(message=message)]

        result = commit.get_suggested_commit_message("diff --git ...")

        returned_body = result.split("\n\n", 1)[1]
        self.assertTrue(
            all(
                len(line) <= commit.COMMIT_BODY_MAX_LINE_LENGTH
                for line in returned_body.splitlines()
            )
        )
        self.assertEqual(mock_completion.call_count, 1)

    @patch("monitor.core.commit.call_litellm_completion")
    @patch("monitor.core.commit.build_commit_message_query_input")
    def test_get_suggested_commit_message_uses_commit_reasoning_overrides(
        self, mock_build, mock_completion
    ):
        """Commit generation should honor commit-specific reasoning overrides."""
        mock_build.return_value = "query_input"
        message = MagicMock()
        message.content = "Suggested commit"
        mock_completion.return_value.choices = [MagicMock(message=message)]

        with patch.object(commit.config, "COMMIT_MODEL", "openai/gpt-5.4"), patch.object(
            commit.config, "COMMIT_REASONING_EFFORT", "high"
        ), patch.object(
            commit.config, "COMMIT_REASONING_MAX_COMPLETION_TOKENS", 8000
        ), patch.object(commit.config, "REASONING_MODEL_PREFIX", "openai/gpt-5"):
            result = commit.get_suggested_commit_message("diff --git ...")

        self.assertEqual(result, "Suggested commit")
        args = mock_completion.call_args.args
        kwargs = mock_completion.call_args.kwargs
        self.assertEqual(args[0], "openai/gpt-5.4")
        self.assertEqual(args[1][0]["role"], "system")
        self.assertEqual(kwargs.get("reasoning_effort"), "high")
        self.assertEqual(kwargs.get("max_completion_tokens"), 8000)

    @patch("monitor.core.commit.call_litellm_completion")
    @patch("monitor.core.commit.build_commit_message_query_input")
    def test_get_suggested_commit_message_routes_ollama_to_native_completion(
        self, mock_build, mock_completion
    ):
        """Ollama commit messages should still use the configured commit model."""
        from monitor import config

        config.COMMIT_MODEL = "ollama/ornith:9b"
        config.MODEL = "ollama/ornith:9b"
        config.REASONING_MODEL_PREFIX = "openai/gpt-5"
        config.COMMIT_REASONING_EFFORT = None
        config.COMMIT_REASONING_MAX_COMPLETION_TOKENS = None
        mock_build.return_value = "query_input"
        message = MagicMock()
        message.content = "Suggested commit"
        mock_completion.return_value.choices = [MagicMock(message=message)]

        result = commit.get_suggested_commit_message("diff --git ...")

        self.assertEqual(result, "Suggested commit")
        args = mock_completion.call_args.args
        kwargs = mock_completion.call_args.kwargs
        self.assertEqual(args[0], "ollama/ornith:9b")
        self.assertEqual(kwargs.get("tool_descriptions"), [])
        self.assertEqual(kwargs.get("gemini_tool_descriptions"), [])

    @patch("os.unlink")
    @patch("monitor.core.commit.subprocess.run")
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
        mock_run,
        mock_unlink,
    ):
        """Edit flow uses edited content for commit and prints success."""
        mock_input.side_effect = ["e", "y"]
        mock_run.return_value = MagicMock(returncode=0)

        # Mock temp file creation (used directly, not as a context manager)
        mock_file = MagicMock()
        mock_file.name = "tempfile"
        mock_tmpfile.return_value = mock_file

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

    @patch("os.unlink")
    @patch("monitor.core.commit.subprocess.run")
    @patch("monitor.core.commit.perform_git_commit")
    @patch("monitor.core.commit.tempfile.NamedTemporaryFile")
    @patch("monitor.core.commit.get_suggested_commit_message", return_value="msg")
    @patch("monitor.core.commit.get_staged_diff", return_value="diff --git ...")
    @patch("monitor.core.commit.input")
    def test_make_commit_command_editor_nonzero_exit_aborts(
        self,
        mock_input,
        mock_get_staged_diff,
        mock_get_suggested,
        mock_tmpfile,
        mock_perform_git_commit,
        mock_run,
        mock_unlink,
    ):
        """A non-zero editor exit aborts the commit and still cleans up the temp file."""
        mock_input.side_effect = ["e"]
        mock_run.return_value = MagicMock(returncode=1)
        mock_file = MagicMock()
        mock_file.name = "tempfile"
        mock_tmpfile.return_value = mock_file

        outputs = []

        def capprint(msg, *a, **k):
            outputs.append(str(msg))

        commit.make_commit_command(print_func=capprint)

        mock_perform_git_commit.assert_not_called()
        mock_unlink.assert_called_once_with("tempfile")  # cleaned up despite abort
        assert any("non-zero status" in o for o in outputs), outputs

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
    @patch("monitor.core.commit.subprocess.run")
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
        mock_run,
        mock_unlink,
    ):
        """Abort when edited message is empty; no commit attempted."""
        mock_input.side_effect = ["e", "y"]
        mock_run.return_value = MagicMock(returncode=0)

        # Mock temp file creation (used directly, not as a context manager)
        mock_file = MagicMock()
        mock_file.name = "tempfile"
        mock_tmpfile.return_value = mock_file

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

    @patch("monitor.core.commit.perform_git_commit")
    @patch("monitor.core.commit.get_suggested_commit_message", side_effect=RuntimeError("rate limited"))
    @patch("monitor.core.commit.get_staged_diff", return_value="diff --git ...")
    def test_make_commit_command_generation_failure_is_friendly(
        self, mock_get_staged_diff, mock_get_suggested, mock_perform_git_commit
    ):
        """A message-generation failure prints a friendly message and commits nothing."""
        outputs = []

        def capprint(msg, *a, **k):
            outputs.append(str(msg))

        commit.make_commit_command(print_func=capprint)
        mock_perform_git_commit.assert_not_called()
        combined = "\n".join(outputs)
        assert "Couldn't generate a commit message" in combined, outputs
        assert "staged changes are untouched" in combined, outputs

    @patch("monitor.core.commit.perform_git_commit")
    @patch("monitor.core.commit.get_suggested_commit_message", side_effect=KeyboardInterrupt)
    @patch("monitor.core.commit.get_staged_diff", return_value="diff --git ...")
    def test_make_commit_command_generation_cancelled_is_friendly(
        self, mock_get_staged_diff, mock_get_suggested, mock_perform_git_commit
    ):
        """Ctrl-C during generation aborts cleanly without a traceback or commit."""
        outputs = []

        def capprint(msg, *a, **k):
            outputs.append(str(msg))

        commit.make_commit_command(print_func=capprint)
        mock_perform_git_commit.assert_not_called()
        assert any("cancelled" in o.lower() for o in outputs), outputs

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
