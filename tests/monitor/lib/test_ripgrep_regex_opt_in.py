"""Tests for the regex opt-in on ripgrep_search / ripgrep_search_tool /
:rg built-in.

Default behavior is unchanged: -F flag is present, patterns are literal.
With regex=True (or --regex on the CLI), -F is dropped and ripgrep
interprets the pattern as a regex — anchors, character classes, alternation.
"""

from unittest.mock import patch, MagicMock

import pytest

# Pre-import config to break a pre-existing import cycle when this test
# file is collected first: ripgrep_search → config → tool_definitions →
# ripgrep_search (mid-load). Loading config first lets it settle.
import monitor.config  # noqa: F401

from monitor.lib import ripgrep_search


def _make_completed_process(stdout="", stderr="", returncode=0):
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


def test_default_uses_fixed_string_flag():
    """Backward-compat: with no regex kwarg, ripgrep_search uses -F."""
    with patch.object(ripgrep_search.subprocess, "run") as mock_run:
        mock_run.return_value = _make_completed_process(stdout="ok\n")
        ripgrep_search.ripgrep_search("foo", use_default_excludes=False)

    cmd = mock_run.call_args[0][0]
    assert "-F" in cmd


def test_regex_true_drops_fixed_string_flag():
    """The headline change: regex=True omits -F so ripgrep interprets the
    pattern as a regex. This is what makes `^def test_` work."""
    with patch.object(ripgrep_search.subprocess, "run") as mock_run:
        mock_run.return_value = _make_completed_process(stdout="ok\n")
        ripgrep_search.ripgrep_search("^def test_", regex=True, use_default_excludes=False)

    cmd = mock_run.call_args[0][0]
    assert "-F" not in cmd
    # The pattern is still passed to ripgrep.
    assert "^def test_" in cmd


def test_regex_false_explicit_still_fixed_string():
    """Passing regex=False explicitly behaves like the default."""
    with patch.object(ripgrep_search.subprocess, "run") as mock_run:
        mock_run.return_value = _make_completed_process(stdout="ok\n")
        ripgrep_search.ripgrep_search("foo", regex=False, use_default_excludes=False)

    cmd = mock_run.call_args[0][0]
    assert "-F" in cmd


def test_ripgrep_search_tool_forwards_regex_flag():
    """The LLM-callable wrapper passes regex through to ripgrep_search."""
    with patch.object(ripgrep_search.subprocess, "run") as mock_run:
        mock_run.return_value = _make_completed_process(stdout="ok\n")
        ripgrep_search.ripgrep_search_tool("^TODO|^FIXME", regex=True)

    cmd = mock_run.call_args[0][0]
    assert "-F" not in cmd
    assert "^TODO|^FIXME" in cmd


def test_grep_command_regex_long_flag():
    """:rg --regex 'pattern' drops -F."""
    with patch.object(ripgrep_search.subprocess, "run") as mock_run:
        mock_run.return_value = _make_completed_process(stdout="ok\n")
        ripgrep_search.grep_command("--regex '^def test_'")

    cmd = mock_run.call_args[0][0]
    assert "-F" not in cmd


def test_grep_command_regex_short_flag():
    """:rg -e 'pattern' is the short-flag equivalent of --regex."""
    with patch.object(ripgrep_search.subprocess, "run") as mock_run:
        mock_run.return_value = _make_completed_process(stdout="ok\n")
        ripgrep_search.grep_command("-e 'TODO|FIXME'")

    cmd = mock_run.call_args[0][0]
    assert "-F" not in cmd


def test_grep_command_without_regex_flag_stays_fixed_string():
    """Existing :rg usage without --regex/-e is unchanged."""
    with patch.object(ripgrep_search.subprocess, "run") as mock_run:
        mock_run.return_value = _make_completed_process(stdout="ok\n")
        ripgrep_search.grep_command("foo py")

    cmd = mock_run.call_args[0][0]
    assert "-F" in cmd


def test_grep_command_regex_with_filetype():
    """Combining --regex with a filetype arg works as expected."""
    with patch.object(ripgrep_search.subprocess, "run") as mock_run:
        mock_run.return_value = _make_completed_process(stdout="ok\n")
        ripgrep_search.grep_command("--regex '^def test_' py")

    cmd = mock_run.call_args[0][0]
    assert "-F" not in cmd
    assert "-t" in cmd
    assert "py" in cmd
