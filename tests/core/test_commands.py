import pytest
from unittest.mock import patch, MagicMock
from monitor.core import commands

# Mock get_first_word, handle_error, run_subprocess globally for test safety
def setup_module(module):
    module._get_first_word_patcher = patch('monitor.core.commands.get_first_word', lambda c: c.split()[0] if c.split() else "")
    module._get_first_word_patcher.start()
    module._handle_error_patcher = patch('monitor.core.commands.handle_error')
    module._mock_handle_error = module._handle_error_patcher.start()
    module._run_subprocess_patcher = patch('monitor.core.commands.run_subprocess', return_value=(0, 'output', '', MagicMock(communicate=lambda: ("proc-out", ""), wait=lambda: None)))
    module._run_subprocess_patcher.start()

def teardown_module(module):
    module._get_first_word_patcher.stop()
    module._handle_error_patcher.stop()
    module._run_subprocess_patcher.stop()

@patch('monitor.core.commands.INTERACTIVE_COMMANDS', [ {'command': 'foo', 'expansion': 'expandme'} ])
def test_is_interactive_command_found():
    cmd = commands.is_interactive_command('foo')
    assert cmd['expansion'] == 'expandme'

@patch('monitor.core.commands.INTERACTIVE_COMMANDS', [ {'command': 'foo', 'expansion': 'expandme'} ])
def test_is_interactive_command_not_found():
    cmd = commands.is_interactive_command('bar')
    assert cmd is None

@patch('monitor.core.commands.INTERNAL_COMMANDS', [{'command': 'bar', 'expansion': 'someexp'}], create=True)
def test_is_internal_command_found():
    with patch('monitor.core.commands.INTERNAL_COMMANDS', [{'command': 'bar', 'expansion': 'someexp'}]):
        cmd = commands.is_internal_command('bar')
        assert cmd['expansion'] == 'someexp'

def test_is_internal_command_not_found():
    with patch('monitor.core.commands.INTERNAL_COMMANDS', [{'command': 'baz', 'expansion': 'x'}]):
        cmd = commands.is_internal_command('bar')
        assert cmd is None

@patch('monitor.core.commands.INTERACTIVE_COMMANDS', [ {'command': 'foo', 'expansion': 'echo work'} ])
def test_execute_interactive_command_success():
    # No crash, runs subprocess, can be called
    commands.execute_interactive_command('foo hi')

@patch('monitor.core.commands.handle_error')
@patch('monitor.core.commands.run_subprocess', side_effect=Exception('fail-eic'))
def test_execute_interactive_command_fail(mock_run, mock_err):
    # If run_subprocess errors, handle_error is called
    commands.INTERACTIVE_COMMANDS = [ {'command': 'failme', 'expansion': 'echo out'} ]
    commands.execute_interactive_command('failme argz')
    mock_err.assert_called()

@patch('monitor.core.commands.PUBLIC_COMMANDS', [ {'command': 'h1'}, {'command': 'h2'} ])
def test_print_interactive_commands(capsys):
    commands.print_interactive_commands(None)
    out = capsys.readouterr().out
    assert 'h1' in out and 'h2' in out
    assert '***' in out

@patch('monitor.core.commands.INTERNAL_COMMANDS', [{'command': 'bar', 'expansion': 'exp', 'internalize': True}])
@patch('monitor.core.commands.recursive_macro_expand', lambda exp, *_: exp)
def test_execute_internal_command_internalize():
    display = MagicMock()
    commands.execute_internal_command('bar somearg', display)
    display.assert_called_with('output')

@patch('monitor.core.commands.INTERNAL_COMMANDS', [{'command': 'bar', 'expansion': '!<echo raw', 'internalize': False}])
def test_execute_internal_command_no_macro():
    display = MagicMock()
    with patch('monitor.core.commands.run_subprocess', return_value=(0, 'plain', '', None)):
        commands.execute_internal_command('bar k', display)

@patch('monitor.core.commands.INTERNAL_COMMANDS', [{'command': 'bar', 'expansion': 'exp', 'internalize': False}])
def test_execute_internal_command_exitcode_warns():
    display = MagicMock()
    # exit_code != 0, stderr returned
    with patch('monitor.core.commands.run_subprocess', return_value=(1, 'pl', 'err!', None)) as msub, \
         patch('monitor.core.commands.logger') as mocklog:
        commands.execute_internal_command('bar', display)
        assert mocklog.warning.called

@patch('monitor.core.commands.INTERNAL_COMMANDS', [{'command': 'notfound', 'expansion': 'exp', 'internalize': False}])
def test_execute_internal_command_unknown():
    display = MagicMock()
    commands.execute_internal_command('noexist foo', display)
    # handle_error should have been called for unknown internal
    from monitor.core import commands as cmds
    assert cmds.handle_error.called

@patch('monitor.core.commands.INTERNAL_COMMANDS', [{'command': 'exp', 'expansion': 'bad', 'internalize': True}])
@patch('monitor.core.commands.recursive_macro_expand', side_effect=Exception('macrofail'))
def test_execute_internal_command_macro_error(mock_macro):
    display = MagicMock()
    # We expect handle_error to be called
    commands.execute_internal_command('exp foo', display)

@patch('monitor.core.commands.INTERNAL_COMMANDS', [{'command': 'llm<', 'expansion': '', 'llm_eval': True}])
def test_llm_internal_command_success():
    # Arrange
    shell_code = "echo hello"
    prompt = "Explain this"
    cmd_line = f"llm< {shell_code} >llm {prompt}"
    display = MagicMock()
    # Patch at both possible locations, just in case:
    with patch('monitor.core.commands.run_subprocess', return_value=(0, "some shell output", "", None)) as mock_run, \
         patch('monitor.core.commands.query', return_value="llm result") as mock_query, \
         patch('monitor.core.commands.logger'):
        commands.execute_internal_command(cmd_line, display)
        # Run checks
        assert mock_run.call_count == 1
        assert "echo hello" in mock_run.call_args[0][0]
        assert mock_query.called, "query was not called -- ensure patch path matches actual import location in commands.py"
        display.assert_called_once_with("llm result")

@patch('monitor.core.commands.INTERNAL_COMMANDS', [{'command': 'llm<', 'expansion': '', 'llm_eval': True}])
def test_llm_internal_command_missing_shell():
    # Arrange: no shell code before >llm, should handle error
    cmd_line = "llm<   >llm why is this broken"
    display = MagicMock()
    with patch('monitor.core.commands.handle_error') as mock_handle_error, \
         patch('monitor.core.commands.logger') as mock_logger:
        commands.execute_internal_command(cmd_line, display)
        mock_handle_error.assert_called_once()
