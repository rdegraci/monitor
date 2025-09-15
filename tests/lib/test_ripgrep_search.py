import pytest
from unittest.mock import patch, MagicMock
from monitor.lib import ripgrep_search
import re

def make_result(stdout='', stderr='', returncode=0):
    mock = MagicMock()
    mock.stdout = stdout
    mock.stderr = stderr
    mock.returncode = returncode
    return mock

@patch('monitor.lib.ripgrep_search.subprocess.run')
def test_ripgrep_search_basic_pattern(mock_run):
    mock_run.return_value = make_result('foo.py:42: hello world', '', 0)
    result = ripgrep_search.ripgrep_search('hello')
    assert 'hello world' in result
    mock_run.assert_called()

@patch('monitor.lib.ripgrep_search.subprocess.run')
def test_ripgrep_search_with_filetype(mock_run):
    mock_run.return_value = make_result('foo.py:42: hello world', '', 0)
    result = ripgrep_search.ripgrep_search('hello', filetype='py')
    assert 'hello world' in result
    args_used = mock_run.call_args[0][0]
    assert '-t' in args_used and 'py' in args_used

@patch('monitor.lib.ripgrep_search.subprocess.run')
def test_ripgrep_search_no_matches(mock_run):
    mock_run.return_value = make_result('', '', 1)
    result = ripgrep_search.ripgrep_search('somethingnotfound')
    assert result == 'No matches found. Searched for: somethingnotfound'

@patch('monitor.lib.ripgrep_search.subprocess.run')
def test_ripgrep_search_unknown_filetype_error(mock_run):
    mock_run.return_value = make_result('', 'unknown file type: foo', 1)
    result = ripgrep_search.ripgrep_search('test', filetype='foo')
    assert 'Error: Unknown file type' in result

@patch('monitor.lib.ripgrep_search.subprocess.run')
def test_ripgrep_search_rg_error_returncode_2(mock_run):
    mock_run.return_value = make_result('', 'some ripgrep error', 2)
    result = ripgrep_search.ripgrep_search('foo bar')
    assert str(result).startswith('Error running ripgrep:')
    assert 'some ripgrep error' in str(result)

# Testing grep_command usage/dispatch, which internally calls ripgrep_search
@patch('monitor.lib.ripgrep_search.ripgrep_search')
def test_grep_command_simple(mock_ripgrep_search):
    mock_ripgrep_search.return_value = 'foo.py:42: hello world'
    result = ripgrep_search.grep_command('hello')
    assert 'hello world' in result
    mock_ripgrep_search.assert_called_once_with('hello', None, word=False)

@patch('monitor.lib.ripgrep_search.ripgrep_search')
def test_grep_command_filetype_end_token(mock_ripgrep_search):
    mock_ripgrep_search.return_value = 'foo.py:42: hello world'
    result = ripgrep_search.grep_command('hello py')
    mock_ripgrep_search.assert_called_once_with('hello', 'py', word=False)

@patch('monitor.lib.ripgrep_search.ripgrep_search')
def test_grep_command_multiword_quoted(mock_ripgrep_search):
    mock_ripgrep_search.return_value = 'foo.py:1: Multi word search!'
    result = ripgrep_search.grep_command('"Multi word search!" py')
    assert 'Multi word search!' in result
    mock_ripgrep_search.assert_called_once_with('Multi word search!', 'py', word=False)

@patch('monitor.lib.ripgrep_search.ripgrep_search')
def test_grep_command_invalid_args_prints_usage(mock_ripgrep_search, capsys):
    result = ripgrep_search.grep_command('')
    captured = capsys.readouterr().out
    assert 'Usage:\n  :rg' in captured
    assert result is None

@pytest.mark.parametrize('flag', ['-w', '--word-regexp'])
@patch('monitor.lib.ripgrep_search.ripgrep_search')
def test_grep_command_word_flag_sets_word_true(mock_ripgrep_search, flag):
    mock_ripgrep_search.return_value = 'foo.py:42: hello world'
    result = ripgrep_search.grep_command(f'hello {flag} py')
    assert 'hello world' in result
    mock_ripgrep_search.assert_called_once_with('hello', 'py', word=True)

@patch('monitor.lib.ripgrep_search.subprocess.run')
def test_ripgrep_search_word_true_includes_flag_w(mock_run):
    mock_run.return_value = make_result('foo.py:1: hello world', '', 0)
    ripgrep_search.ripgrep_search('hello', word=True)
    args_used = mock_run.call_args[0][0]
    assert '-w' in args_used

@patch('monitor.lib.ripgrep_search.ripgrep_search')
def test_grep_command_quoted_flag_like_is_literal(mock_ripgrep_search):
    mock_ripgrep_search.return_value = 'foo.py:1: -w literal'
    result = ripgrep_search.grep_command('"-w" py')
    assert '-w' in result
    mock_ripgrep_search.assert_called_once_with('-w', 'py', word=False)

@patch('monitor.lib.ripgrep_search.ripgrep_search')
def test_grep_command_end_of_options_treats_tokens_literally(mock_ripgrep_search):
    mock_ripgrep_search.return_value = 'foo.py:1: hello -w py'
    result = ripgrep_search.grep_command('hello -- -w py')
    assert 'hello -w py' in result
    mock_ripgrep_search.assert_called_once_with('hello -w py', None, word=False)

# Test to ensure ripgrep_search_tool passes through args to ripgrep_search and returns the result
@patch('monitor.lib.ripgrep_search.ripgrep_search')
def test_ripgrep_search_tool_passes_through(mock_ripgrep_search):
    mock_ripgrep_search.return_value = 'ok'
    result = ripgrep_search.ripgrep_search_tool('foo', filetype='py', word=True)
    assert result == 'ok'
    mock_ripgrep_search.assert_called_once_with('foo', 'py', '.', True)

# Tests for SAFE_LIMIT truncation behavior
@patch('monitor.lib.ripgrep_search.subprocess.run')
def test_ripgrep_search_truncates_to_default_safe_limit_when_no_base_limit(mock_run, monkeypatch):
    monkeypatch.setattr(ripgrep_search.config, 'base_limit', None, raising=False)
    monkeypatch.setattr(ripgrep_search.config, 'MODEL_CONTEXT_WINDOW', None, raising=False)
    monkeypatch.setattr(ripgrep_search.config, 'MAX_TOKEN_COUNT', 0, raising=False)
    monkeypatch.setattr(ripgrep_search, 'SEARCH_EVALUATION_DIVISOR', 15, raising=False)
    large_output = 'A' * 10000
    mock_run.return_value = make_result(large_output, '', 0)
    result = ripgrep_search.ripgrep_search('A')
    assert isinstance(result, str)
    # Detect optional truncation suffix and compute preserved payload accordingly
    m = re.search(r"\[TRUNCATED (\d+) bytes of output\]", result)
    if m:
        truncated_reported = int(m.group(1))
        preserved_payload = result[:m.start()].rstrip('\n')
    else:
        preserved_payload = result
    assert len(preserved_payload) >= 4096
    assert large_output.startswith(preserved_payload)
    if m:
        truncated_expected = len(large_output) - len(preserved_payload)
        assert truncated_reported == truncated_expected

@patch('monitor.lib.ripgrep_search.subprocess.run')
def test_ripgrep_search_truncates_to_base_limit_divisor(mock_run, monkeypatch):
    monkeypatch.setattr(ripgrep_search.config, 'MODEL_CONTEXT_WINDOW', 10000, raising=False)
    monkeypatch.setattr(ripgrep_search.config, 'MAX_TOKEN_COUNT', 0, raising=False)
    monkeypatch.setattr(ripgrep_search, 'SEARCH_EVALUATION_DIVISOR', 5, raising=False)
    large_output = 'B' * 12000
    mock_run.return_value = make_result(large_output, '', 0)
    result = ripgrep_search.ripgrep_search('B')
    assert isinstance(result, str)
    # With SEARCH_EVALUATION_DIVISOR=5 and MODEL_CONTEXT_WINDOW=10000, expected preserved length is (10000//5)*4 = 8000
    m = re.search(r"\[TRUNCATED (\d+) bytes of output\]", result)
    assert m is not None
    truncated_reported = int(m.group(1))
    preserved_payload = result[:m.start()].rstrip('\n')
    expected_limit = 8000
    assert len(preserved_payload) == expected_limit
    assert large_output.startswith(preserved_payload)
    truncated_expected = len(large_output) - len(preserved_payload)
    assert truncated_reported == truncated_expected
