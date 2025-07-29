
import pytest
from unittest.mock import patch, MagicMock
import logging
from monitor.lib import commit_analyzer

class DummyCommit:
    def __init__(self, message, hexsha, date, diff='diff --git...'):
        self.message = message
        self.hexsha = hexsha
        self.committed_date = date
        self.diff = diff

@patch('monitor.lib.commit_analyzer.litellm.completion')
@patch('monitor.lib.commit_analyzer.perform_git_show')
@patch('monitor.lib.commit_analyzer.perform_git_log_range')
def test_analyze_commits_summary_and_next_steps(mock_log_range, mock_show, mock_litellm):
    """
    Test CommitAnalyzer.analyze_commits and suggest_next_steps provide
    summary and actionable steps for commits in the range with synthetic commit dicts.
    """
    # Setup fake commit data for perform_git_log_range
    dummy_commit_dict = {
        'message': 'Initial commit.',
        'hexsha': 'abc123',
        'committed_date': 1680000000
    }
    mock_log_range.return_value = [dummy_commit_dict]

    dummy_commit_diff = 'diff --git...'
    mock_show.return_value = dummy_commit_diff

    # Fake LLM summary response
    mock_litellm.return_value = MagicMock()
    mock_litellm.return_value.choices = [MagicMock(message=MagicMock(content='Summary of change.\n1. Do X\n2. Do Y'))]

    logger = logging.getLogger('monitor.lib.commit_analyzer.test')
    analyzer = commit_analyzer.CommitAnalyzer('feature-branch', logger, main_branch='main', llm_model='test-model')
    summary, diff = analyzer.analyze_commits()
    assert 'Summary' in summary
    assert 'diff' in diff

    steps = analyzer.suggest_next_steps(summary)
    assert any('Do' in step for step in steps)

@patch('monitor.lib.commit_analyzer.litellm.completion')
@patch('monitor.lib.commit_analyzer.perform_git_show')
@patch('monitor.lib.commit_analyzer.perform_git_log_range')
def test_no_commits_path_returns_warning_and_fallback(mock_log_range, mock_show, mock_litellm):
    """
    Test that analyze_commits returns warning and sensible fallback steps when no commits are present.
    """
    # simulate empty commit list
    mock_log_range.return_value = []
    mock_show.return_value = ''
    logger = logging.getLogger('monitor.lib.commit_analyzer.test')
    analyzer = commit_analyzer.CommitAnalyzer('empty-branch', logger, main_branch='main', llm_model='test-model')
    summary, diff = analyzer.analyze_commits()
    assert 'No commits found' in summary or summary == 'No commits found for analysis. Make sure you\'re on a topic branch that branches off of main/master.'

    steps = analyzer.suggest_next_steps(summary)
    assert isinstance(steps, list)
    assert len(steps) >= 2

@patch('monitor.lib.commit_analyzer.yaml.safe_load', return_value={'branch_name': 'abc', 'main_branch': 'main'})
@patch('builtins.open')
def test_load_config_success(mock_open, mock_safe_load):
    result = commit_analyzer.load_config()
    assert result['branch_name'] == 'abc'
    assert result['main_branch'] == 'main'

@patch('monitor.lib.commit_analyzer.yaml.safe_load', side_effect=Exception('fail'))
@patch('builtins.open', side_effect=FileNotFoundError)
def test_load_config_missing_or_bad_file(mock_open, mock_safe_load):
    result = commit_analyzer.load_config()
    assert result['branch_name'] == 'main'
    assert result['main_branch'] == 'main'

@patch('monitor.lib.commit_analyzer.perform_git_diff_staged', return_value='sample-diff')
@patch('monitor.lib.commit_analyzer.recursive_macro_expand', side_effect=lambda c, v, o, cl, e: c)
def test_build_commit_message_query_input(mock_expand, mock_diff):
    """
    Test that build_commit_message_query_input includes diff text.
    """
    out = commit_analyzer.build_commit_message_query_input({}, '<<', '>>', '\\')
    assert 'sample-diff' in out


