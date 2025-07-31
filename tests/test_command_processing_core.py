import pytest
from unittest.mock import patch, MagicMock
from monitor.core import command_processing

@pytest.fixture(autouse=True)
def patch_config_macros():
    with patch('monitor.core.command_processing.config') as mcfg:
        mcfg.MACRO_DELIMITER_OPEN = '<%'
        mcfg.MACRO_DELIMITER_CLOSE = '%>'
        mcfg.MACRO_DELIMITER_ESCAPE = '~'
        yield

@patch('monitor.core.command_processing.recursive_macro_expand', lambda c, *_: c)
def test_evaluate_command_empty():
    result = command_processing.evaluate_command('')
    assert result.command_type == 'empty'
    assert result.output is None
    assert result.exit_requested is False

@patch('monitor.core.command_processing.recursive_macro_expand', lambda c, *_: c)
def test_evaluate_command_exit():
    result = command_processing.evaluate_command('exit')
    assert result.exit_requested
    assert result.command_type == 'exit'
    result = command_processing.evaluate_command('/exit')
    assert result.exit_requested
    assert result.command_type == 'exit'

@patch('monitor.core.command_processing.recursive_macro_expand', lambda c, *_: c)
@patch('monitor.core.command_processing.handle_cd_command', lambda arg: '/mocked/path')
def test_evaluate_command_cd():
    result = command_processing.evaluate_command('cd somewhere')
    assert result.command_type == 'cd'
    assert result.output == '/mocked/path'

@patch('monitor.core.command_processing.is_interactive_command', lambda c: True)
@patch('monitor.core.command_processing.recursive_macro_expand', lambda c, *_: c)
def test_evaluate_command_unsupported_interactive():
    result = command_processing.evaluate_command('some interactive')
    assert result.command_type == 'unsupported'
    assert result.error

@patch('monitor.core.command_processing.is_interactive_command', lambda c: False)
@patch('monitor.core.command_processing.is_internal_command', lambda c: True)
@patch('monitor.core.command_processing.recursive_macro_expand', lambda c, *_: c)
def test_evaluate_command_unsupported_internal():
    result = command_processing.evaluate_command('some internal')
    assert result.command_type == 'unsupported'
    assert result.error

@patch('monitor.core.command_processing.is_interactive_command', lambda c: False)
@patch('monitor.core.command_processing.is_internal_command', lambda c: False)
@patch('monitor.core.command_processing.is_built_in_function', lambda c: True)
@patch('monitor.core.command_processing.recursive_macro_expand', lambda c, *_: c)
def test_evaluate_command_unsupported_built_in():
    result = command_processing.evaluate_command('builtin something')
    assert result.command_type == 'unsupported'
    assert result.error

@patch('monitor.core.command_processing.is_interactive_command', lambda c: False)
@patch('monitor.core.command_processing.is_internal_command', lambda c: False)
@patch('monitor.core.command_processing.is_built_in_function', lambda c: False)
@patch('monitor.core.command_processing.recursive_macro_expand', lambda c, *_: c)
@patch('monitor.core.command_processing.query', lambda c: 'llm-output')
def test_evaluate_command_llm():
    result = command_processing.evaluate_command('llm-question')
    assert result.command_type == 'llm'
    assert result.output == 'llm-output'

@patch('monitor.core.command_processing.logger')
def test_evaluate_command_exception(mock_logger):
    with patch('monitor.core.command_processing.recursive_macro_expand', side_effect=Exception('fail')):
        result = command_processing.evaluate_command('will error')
    assert result.command_type == 'error'
    assert 'fail' in result.error

# process_macro_command tests
@patch('monitor.core.command_processing.logger')
@patch('monitor.core.command_processing.display_query_result')
@patch('monitor.core.command_processing.recursive_macro_expand', lambda c, *_: 'expanded!')
def test_process_macro_command_executes(mock_disp, mock_logger):
    out = command_processing.process_macro_command('<(macro);')
    mock_disp.assert_called_with('expanded!')
    assert out is True

def test_process_macro_command_non_macro():
    out = command_processing.process_macro_command('not a macro')
    assert out is False

# handle_exit_command tests
@patch('monitor.core.command_processing.signal')
@patch('monitor.core.command_processing.logger')
@patch('monitor.core.command_processing.yellow', 'Y')
@patch('monitor.core.command_processing.reset', 'R')
def test_handle_exit_command_exit(mock_logger, mock_signal):
    assert command_processing.handle_exit_command('exit') == True
    mock_signal.signal.assert_not_called()
    assert command_processing.handle_exit_command('/exit') == True
    mock_signal.signal.assert_called()
    assert command_processing.handle_exit_command('other cmd') == False

# process_cd_command
@patch('monitor.core.command_processing.handle_cd_command', lambda arg: '/here')
@patch('monitor.core.command_processing.logger')
@patch('monitor.core.command_processing.query')
def test_process_cd_command_trigger(mock_query, mock_logger):
    assert command_processing.process_cd_command('cd path', 'cd') is True
    mock_query.assert_called_with('Be aware I have changed directory to /here')
    assert command_processing.process_cd_command('other cmd', 'other') is False

# internalize_command is a forwarding wrapper
@patch('monitor.core.command_processing.evaluate_command', lambda x: MagicMock(output='result'))
def test_internalize_command():
    assert command_processing.internalize_command('abc') == 'result'
