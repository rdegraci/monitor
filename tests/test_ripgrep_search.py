import pytest
from unittest.mock import patch, MagicMock
from monitor.lib import ripgrep_search

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
    assert result == 'No matches found.'

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
