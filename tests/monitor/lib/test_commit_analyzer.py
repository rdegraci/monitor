import logging

import pytest
from unittest.mock import MagicMock, patch

from monitor.lib import commit_analyzer

LOGGER = logging.getLogger("monitor.lib.commit_analyzer.test")


def _llm(content):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


@patch("monitor.lib.commit_analyzer.llm_utils.call_litellm_completion")
@patch("monitor.lib.commit_analyzer.run_git_capture")
def test_analyze_and_next_steps_happy_path(mock_git, mock_llm):
    """Summary then next-steps; the diff is sent to the LLM only once (not re-sent)."""
    mock_git.return_value = ("commit abc\n+new_code_line\n", "", None)
    mock_llm.side_effect = [_llm("This branch adds X."), _llm("1. Do X\n2. Do Y")]

    analyzer = commit_analyzer.CommitAnalyzer("feature", LOGGER, main_branch="main", llm_model="test-model")
    assert analyzer.has_commits is True
    assert analyzer.fetch_error is None

    summary, diff = analyzer.analyze_commits()
    assert summary == "This branch adds X."
    assert "diff" in diff or "new_code_line" in diff  # colorized commit log

    steps = analyzer.suggest_next_steps(summary)
    assert steps == ["Do X", "Do Y"]

    # The next-steps prompt must not re-embed the diff (sent once in analyze_commits).
    next_steps_prompt = mock_llm.call_args_list[1].args[1][0]["content"]
    assert "new_code_line" not in next_steps_prompt


@patch("monitor.lib.commit_analyzer.run_git_capture")
def test_fetch_error_is_recorded(mock_git):
    """A git failure is captured as fetch_error, not silently treated as empty."""
    mock_git.return_value = (None, None, "An error occurred ...: fatal: bad revision 'nope'")
    analyzer = commit_analyzer.CommitAnalyzer("nope", LOGGER, main_branch="main", llm_model="m")
    assert analyzer.has_commits is False
    assert analyzer.fetch_error and "bad revision" in analyzer.fetch_error


@patch("monitor.lib.commit_analyzer.run_git_capture")
def test_no_commits_yields_message_and_no_fabricated_steps(mock_git):
    """An empty range yields a clear message and NO fabricated next steps."""
    mock_git.return_value = ("", "", None)
    analyzer = commit_analyzer.CommitAnalyzer("empty", LOGGER, main_branch="main", llm_model="m")
    summary, _ = analyzer.analyze_commits()
    assert "No commits found" in summary
    assert analyzer.suggest_next_steps(summary) == []


@patch("monitor.lib.commit_analyzer.llm_utils.call_litellm_completion", side_effect=RuntimeError("api down"))
@patch("monitor.lib.commit_analyzer.run_git_capture")
def test_analyze_commits_raises_on_llm_error(mock_git, mock_llm):
    """LLM failure propagates instead of returning a placeholder summary."""
    mock_git.return_value = ("commit abc\n+code\n", "", None)
    analyzer = commit_analyzer.CommitAnalyzer("feature", LOGGER, main_branch="main", llm_model="m")
    with pytest.raises(RuntimeError):
        analyzer.analyze_commits()


@patch("monitor.lib.commit_analyzer.llm_utils.call_litellm_completion", side_effect=RuntimeError("api down"))
@patch("monitor.lib.commit_analyzer.run_git_capture")
def test_suggest_next_steps_raises_on_llm_error_no_fabrication(mock_git, mock_llm):
    """LLM failure propagates instead of returning fabricated generic steps."""
    mock_git.return_value = ("commit abc\n+code\n", "", None)
    analyzer = commit_analyzer.CommitAnalyzer("feature", LOGGER, main_branch="main", llm_model="m")
    with pytest.raises(RuntimeError):
        analyzer.suggest_next_steps("some summary")


@patch("monitor.lib.commit_analyzer.llm_utils.call_litellm_completion")
@patch("monitor.lib.commit_analyzer.run_git_capture")
def test_commit_log_is_capped(mock_git, mock_llm):
    """A huge commit log is truncated before going to the LLM."""
    big = "x" * (commit_analyzer.MAX_COMMIT_LOG_CHARS + 5000)
    mock_git.return_value = (big, "", None)
    analyzer = commit_analyzer.CommitAnalyzer("feature", LOGGER, main_branch="main", llm_model="m")
    assert len(analyzer.commit_log) <= commit_analyzer.MAX_COMMIT_LOG_CHARS + 100
    assert "truncated" in analyzer.commit_log


@patch("monitor.lib.commit_analyzer.run_git_capture")
def test_analyze_branch_raises_on_fetch_error(mock_git):
    mock_git.return_value = (None, None, "fatal: bad revision")
    with pytest.raises(RuntimeError):
        commit_analyzer.analyze_branch_for_summary_and_steps(
            "nope", LOGGER, model="m", main_branch="main"
        )


def test_parse_steps_handles_varied_markers():
    out = commit_analyzer._parse_steps("1. alpha\n2) beta\n- gamma\n* delta\n• epsilon")
    assert out == ["alpha", "beta", "gamma", "delta", "epsilon"]


def test_parse_steps_falls_back_to_raw_when_no_markers():
    assert commit_analyzer._parse_steps("just some prose") == ["just some prose"]


@patch("monitor.lib.commit_analyzer.recursive_macro_expand", side_effect=lambda c, v, o, cl, e: c)
def test_build_commit_message_query_input(mock_expand):
    out = commit_analyzer.build_commit_message_query_input("sample-diff", {}, "<<", ">>", "\\")
    assert "sample-diff" in out
