import pytest
import logging
from unittest.mock import patch, MagicMock
from monitor.lib import git

# Patch run_git_capture throughout these tests to avoid hitting real git

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_status_success(mock_run):
    mock_run.return_value = ('On branch main\nnothing to commit\n', '', None)
    output = git.perform_git_status()
    assert 'On branch main' in output
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert cmd == ['git', '--no-pager', 'status']

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_status_failure(mock_run):
    mock_run.return_value = ('', '', 'An error occurred while executing git --no-pager status: fatal: not a git repository')
    output = git.perform_git_status()
    assert 'fatal' in output.lower()
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert cmd == ['git', '--no-pager', 'status']

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_diff_no_changes(mock_run):
    mock_run.return_value = ('', '', None)
    output = git.perform_git_diff()
    assert 'no changes' in output.lower()
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert cmd[:3] == ['git', '--no-pager', 'diff']
    assert len(cmd) == 3

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_diff_repo_success(mock_run):
    mock_run.return_value = ('diff --git a/file b/file\n...', '', None)
    output = git.perform_git_diff()
    assert 'diff --git' in output
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert cmd[:3] == ['git', '--no-pager', 'diff']

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_diff_file_invalid_path(mock_run):
    output = git.perform_git_diff_file('')
    assert 'invalid' in output.lower()
    mock_run.assert_not_called()

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_diff_file_success(mock_run):
    mock_run.return_value = ('diff --git a/app.py b/app.py\n...', '', None)
    output = git.perform_git_diff_file('app.py')
    assert 'diff --git' in output
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == 'git' and 'diff' in cmd and '--no-pager' in cmd
    assert cmd[-1] == 'app.py'

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_diff_previous_success(mock_run):
    mock_run.return_value = ('diff --git a/app.py b/app.py\n...', '', None)
    output = git.perform_git_diff_previous()
    assert 'diff --git' in output
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert cmd == ['git', '--no-pager', 'diff', 'HEAD^..HEAD']

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_diff_staged_success(mock_run):
    mock_run.return_value = ('diff --git a/app.py b/app.py\n...', '', None)
    output = git.perform_git_diff_staged()
    assert 'diff --git' in output
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == 'git' and 'diff' in cmd and '--no-pager' in cmd
    assert '--cached' in cmd or '--staged' in cmd

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_show_success(mock_run):
    mock_run.return_value = ('commit abc123\nAuthor: Someone', '', None)
    output = git.perform_git_show('abc123')
    assert 'commit abc123' in output
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == 'git'
    assert '--no-pager' in cmd
    assert 'show' in cmd
    assert 'abc123' in cmd

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_show_invalid_ref(mock_run):
    output = git.perform_git_show('')
    assert 'invalid' in output.lower()
    mock_run.assert_not_called()

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_log_success(mock_run):
    mock_run.return_value = ('abc123 First commit\nbcd234 Second commit', '', None)
    output = git.perform_git_log()
    assert 'commit' in output.lower() or 'abc123' in output
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == 'git' and 'log' in cmd
    assert '--no-pager' in cmd

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_commit_success(mock_run):
    mock_run.return_value = ('[main abc123] Add feature', '', None)
    output = git.perform_git_commit('Add feature')
    assert 'add feature' in output.lower() or '[' in output
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == 'git' and cmd[1] == 'commit'
    assert '-m' in cmd
    assert 'Add feature' in cmd

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_commit_invalid_message(mock_run):
    output = git.perform_git_commit('')
    assert 'non-empty string' in output.lower()
    mock_run.assert_not_called()

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_stash_success(mock_run):
    mock_run.return_value = ('Saved working directory and index state', '', None)
    output = git.perform_git_stash('push')
    assert 'saved' in output.lower() or 'stash' in output.lower()
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == 'git' and 'stash' in cmd
    assert 'push' in cmd

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_stash_no_subcommand(mock_run):
    output = git.perform_git_stash(None)
    assert 'subcommand' in output.lower() or 'invalid' in output.lower()
    mock_run.assert_not_called()

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_log_range_success(mock_run):
    mock_run.side_effect = [
        ('abc000', '', None),  # merge-base output (base commit)
        ('abc123\x1fFirst commit\x1f1688169600\nbcd234\x1fSecond commit\x1f1688256000', '', None),  # log output with unit separator
    ]
    output = git.perform_git_log_range('abc123', 'def456')
    assert isinstance(output, list)
    assert all(isinstance(c, dict) for c in output)
    assert mock_run.call_count == 2
    calls = mock_run.call_args_list
    cmd1 = calls[0][0][0]
    cmd2 = calls[1][0][0]
    assert cmd1[0] == 'git' and cmd1[1] == 'merge-base'
    assert 'abc123' in cmd1 and 'def456' in cmd1
    assert cmd2[0] == 'git' and 'log' in cmd2
    assert '--no-pager' in cmd2
    assert any('..' in part for part in cmd2)

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_log_range_merge_base_failure(mock_run):
    mock_run.return_value = ('', 'error determining merge base', 'error')
    output = git.perform_git_log_range('abc123', 'def456')
    assert isinstance(output, list) and output == []
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == 'git' and cmd[1] == 'merge-base'
    assert 'abc123' in cmd and 'def456' in cmd

@patch('monitor.lib.git.run_git_capture')
def test_perform_git_log_range_log_failure(mock_run):
    mock_run.side_effect = [
        ('abc000', '', None),
        ('', 'error getting log', 'error'),
    ]
    output = git.perform_git_log_range('abc123', 'def456')
    assert isinstance(output, list) and output == []
    assert mock_run.call_count == 2
    calls = mock_run.call_args_list
    cmd1 = calls[0][0][0]
    cmd2 = calls[1][0][0]
    assert cmd1[0] == 'git' and cmd1[1] == 'merge-base'
    assert cmd2[0] == 'git' and 'log' in cmd2
    assert '--no-pager' in cmd2
