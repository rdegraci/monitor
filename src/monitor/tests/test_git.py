import pytest
import logging
from unittest.mock import patch, MagicMock
from monitor.lib import git

# Patch subprocess.run throughout these tests to avoid hitting real git

@patch('lib.git.subprocess.run')
def test_perform_git_status_success(mock_run):
    mock_result = MagicMock(stdout='On branch main\nnothing to commit\n', returncode=0)
    mock_run.return_value = mock_result
    output = git.perform_git_status()
    assert 'On branch main' in output
    mock_run.assert_called_once_with(['git', 'status'], check=True, text=True, capture_output=True)
    
@patch('lib.git.subprocess.run')
def test_perform_git_status_failure(mock_run):
    mock_run.side_effect = git.subprocess.CalledProcessError(1, 'git status')
    output = git.perform_git_status()
    assert 'An error occurred while executing git status' in output

@patch('lib.git.subprocess.run')
def test_perform_git_diff_no_changes(mock_run):
    mock_result = MagicMock(stdout='', returncode=0)
    mock_run.return_value = mock_result
    output = git.perform_git_diff()
    assert output == 'No changes detected.'

@patch('lib.git.subprocess.run')
def test_perform_git_diff_file_invalid_path(mock_run):
    output = git.perform_git_diff_file('')
    assert 'Invalid path provided' in output
    mock_run.assert_not_called()

@patch('lib.git.subprocess.run')
def test_perform_git_diff_previous_success(mock_run):
    mock_result = MagicMock(stdout='diff --git ...', returncode=0)
    mock_run.return_value = mock_result
    output = git.perform_git_diff_previous()
    assert 'diff --git' in output

@patch('lib.git.subprocess.run')
def test_perform_git_show_success(mock_run):
    mock_result = MagicMock(stdout='commit abc123\nAuthor: Someone', returncode=0)
    mock_run.return_value = mock_result
    output = git.perform_git_show('abc123')
    assert 'commit abc123' in output

@patch('lib.git.subprocess.run')
def test_perform_git_show_invalid_ref(mock_run):
    output = git.perform_git_show('')
    assert 'Invalid ref provided' in output
    mock_run.assert_not_called()

@patch('lib.git.subprocess.run')
def test_perform_git_diff_staged_success(mock_run):
    mock_result = MagicMock(stdout='diff --git ...', returncode=0)
    mock_run.return_value = mock_result
    output = git.perform_git_diff_staged()
    assert 'diff --git' in output
