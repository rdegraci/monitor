"""Tests for the read-only git history-search tools (pickaxe + blame)."""

import subprocess
from unittest.mock import MagicMock, patch

from monitor.lib import git_history


def _completed(stdout="", stderr="", returncode=0):
    return MagicMock(stdout=stdout, stderr=stderr, returncode=returncode)


# --- search_commit_history (pickaxe) ----------------------------------------


@patch("monitor.lib.git_history.subprocess.run")
def test_search_uses_pickaxe_S_glued_and_dash_dash(mock_run):
    mock_run.return_value = _completed(stdout="abc123 2026-05-01 Add parser\n")
    out = git_history.search_commit_history("parse_tokens")

    cmd = mock_run.call_args.args[0]
    assert "-Sparse_tokens" in cmd  # glued so a leading-dash query is safe
    assert cmd[-1] == "--"  # no path -> ends with the separator
    assert mock_run.call_args.kwargs["timeout"] == git_history.HISTORY_TIMEOUT_SECONDS
    assert "Add parser" in out


@patch("monitor.lib.git_history.subprocess.run")
def test_search_regex_uses_G_and_scopes_path(mock_run):
    mock_run.return_value = _completed(stdout="def123 2026-04-02 Tweak\n")
    git_history.search_commit_history("foo.*bar", regex=True, path="src/app.py")

    cmd = mock_run.call_args.args[0]
    assert "-Gfoo.*bar" in cmd
    assert cmd[-2] == "--" and cmd[-1] == "src/app.py"  # path after the separator


@patch("monitor.lib.git_history.subprocess.run")
def test_search_empty_query_errors_without_running(mock_run):
    out = git_history.search_commit_history("   ")
    assert out.startswith("Error:")
    mock_run.assert_not_called()


@patch("monitor.lib.git_history.subprocess.run")
def test_search_no_matches_message(mock_run):
    mock_run.return_value = _completed(stdout="")
    out = git_history.search_commit_history("nonexistent")
    assert "No commits found" in out


@patch("monitor.lib.git_history.subprocess.run")
def test_search_nonzero_returncode_surfaces_stderr(mock_run):
    mock_run.return_value = _completed(stderr="fatal: not a git repository", returncode=128)
    out = git_history.search_commit_history("x")
    assert "Error running git log" in out
    assert "not a git repository" in out


@patch("monitor.lib.git_history.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30))
def test_search_timeout(mock_run):
    out = git_history.search_commit_history("x")
    assert "timed out" in out


# --- blame_lines ------------------------------------------------------------


@patch("monitor.lib.git_history.subprocess.run")
def test_blame_builds_L_range_and_dash_dash(mock_run):
    mock_run.return_value = _completed(stdout="abc123 (Dev 2026-05-01 10) code\n")
    out = git_history.blame_lines("src/app.py", 10, 20)

    cmd = mock_run.call_args.args[0]
    assert "-L" in cmd and "10,20" in cmd
    assert cmd[-2] == "--" and cmd[-1] == "src/app.py"
    assert mock_run.call_args.kwargs["timeout"] == git_history.HISTORY_TIMEOUT_SECONDS
    assert "code" in out


@patch("monitor.lib.git_history.subprocess.run")
def test_blame_rejects_bad_range(mock_run):
    assert git_history.blame_lines("f.py", 0, 5).startswith("Error:")
    assert git_history.blame_lines("f.py", 5, 2).startswith("Error:")
    assert git_history.blame_lines("f.py", "x", 5).startswith("Error:")
    mock_run.assert_not_called()


@patch("monitor.lib.git_history.subprocess.run")
def test_blame_missing_path_errors(mock_run):
    assert git_history.blame_lines("", 1, 5).startswith("Error:")
    mock_run.assert_not_called()


@patch("monitor.lib.git_history.subprocess.run")
def test_blame_nonzero_returncode_surfaces_stderr(mock_run):
    mock_run.return_value = _completed(stderr="fatal: no such path", returncode=128)
    out = git_history.blame_lines("missing.py", 1, 5)
    assert "Error running git blame" in out


# --- perform_git_diff_range -------------------------------------------------


@patch("monitor.lib.git_history.subprocess.run")
def test_diff_range_builds_command_with_dash_dash(mock_run):
    mock_run.return_value = _completed(stdout="diff --git a/x b/x\n+added\n")
    out = git_history.perform_git_diff_range("v1.0", "HEAD")

    cmd = mock_run.call_args.args[0]
    assert cmd[:5] == ["git", "--no-pager", "diff", "v1.0", "HEAD"]
    assert cmd[-1] == "--"  # no path -> ends with separator
    assert mock_run.call_args.kwargs["timeout"] == git_history.HISTORY_TIMEOUT_SECONDS
    assert "+added" in out


@patch("monitor.lib.git_history.subprocess.run")
def test_diff_range_scopes_path_after_separator(mock_run):
    mock_run.return_value = _completed(stdout="diff\n")
    git_history.perform_git_diff_range("abc", "def", path="src/app.py")
    cmd = mock_run.call_args.args[0]
    assert cmd[-2] == "--" and cmd[-1] == "src/app.py"


@patch("monitor.lib.git_history.subprocess.run")
def test_diff_range_requires_both_refs(mock_run):
    assert git_history.perform_git_diff_range("", "HEAD").startswith("Error:")
    assert git_history.perform_git_diff_range("HEAD", "  ").startswith("Error:")
    mock_run.assert_not_called()


@patch("monitor.lib.git_history.subprocess.run")
def test_diff_range_rejects_leading_dash_refs(mock_run):
    out = git_history.perform_git_diff_range("--output=/etc/x", "HEAD")
    assert out.startswith("Error:")
    mock_run.assert_not_called()


@patch("monitor.lib.git_history.subprocess.run")
def test_diff_range_no_differences_message(mock_run):
    mock_run.return_value = _completed(stdout="")
    out = git_history.perform_git_diff_range("HEAD", "HEAD")
    assert "No differences between HEAD and HEAD" in out


@patch("monitor.lib.git_history.subprocess.run")
def test_diff_range_nonzero_returncode_surfaces_stderr(mock_run):
    mock_run.return_value = _completed(stderr="fatal: bad revision 'nope'", returncode=128)
    out = git_history.perform_git_diff_range("nope", "HEAD")
    assert "Error running git diff" in out
    assert "bad revision" in out


@patch("monitor.lib.git_history.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30))
def test_diff_range_timeout(mock_run):
    assert "timed out" in git_history.perform_git_diff_range("a", "b")
