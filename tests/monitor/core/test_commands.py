import pytest
from unittest.mock import patch, MagicMock
from monitor.core import commands

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
    with patch('monitor.core.commands.run_subprocess', return_value=(0, 'output', '', None)):
        commands.execute_interactive_command('foo hi')

@patch('monitor.core.commands.handle_error')
@patch('monitor.core.commands.run_subprocess', side_effect=Exception('fail-eic'))
def test_execute_interactive_command_fail(mock_run, mock_err):
    # If run_subprocess errors, handle_error is called
    commands.INTERACTIVE_COMMANDS = [ {'command': 'failme', 'expansion': 'echo out'} ]
    commands.execute_interactive_command('failme argz')
    mock_err.assert_called()

@patch('monitor.core.commands.ALL_TERMINAL_COMMANDS', [ {'command': 'h1'}, {'command': 'h2'} ])
def test_print_terminal_commands(capsys):
    commands.print_terminal_commands(None)
    out = capsys.readouterr().out
    assert 'h1' in out and 'h2' in out
    assert '***' in out

@patch('monitor.core.commands.INTERNAL_COMMANDS', [{'command': 'bar', 'expansion': 'exp', 'internalize': True}])
@patch('monitor.core.commands.recursive_macro_expand', lambda exp, *_: exp)
def test_execute_internal_command_internalize():
    display = MagicMock()
    with patch('monitor.core.commands.run_subprocess', return_value=(0, 'output', '', None)):
        commands.execute_internal_command('bar somearg', display)
    display.assert_called_with('output')

@patch('monitor.core.commands.INTERNAL_COMMANDS', [{'command': 'bar', 'expansion': '!<echo raw', 'internalize': False}])
def test_execute_internal_command_no_macro():
    display = MagicMock()
    with patch('monitor.core.commands.run_subprocess', return_value=(0, 'plain', '', None)) as mock_run:
        commands.execute_internal_command('bar k', display)
        # Ensure run_subprocess was called with args list for zsh (shell=False)
        assert isinstance(mock_run.call_args[0][0], list)
        payload = mock_run.call_args[0][0][2]
        assert 'echo raw' in payload and 'k' in payload

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
    with patch('monitor.core.commands.handle_error') as mock_handle_error:
        commands.execute_internal_command('noexist foo', display)
        mock_handle_error.assert_called()

@patch('monitor.core.commands.INTERNAL_COMMANDS', [{'command': 'exp', 'expansion': 'bad', 'internalize': True}])
@patch('monitor.core.commands.recursive_macro_expand', side_effect=Exception('macrofail'))
def test_execute_internal_command_macro_error(mock_macro):
    display = MagicMock()
    with patch('monitor.core.commands.handle_error') as mock_handle_error:
        commands.execute_internal_command('exp foo', display)
        assert mock_handle_error.called

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


# --- command_needs_tty -------------------------------------------------------

@pytest.fixture
def _isolated_command_lists(monkeypatch):
    """Empty all command lists so needs_tty tests only see what they inject."""
    monkeypatch.setattr(commands, "PRIVATE_COMMANDS", [])
    monkeypatch.setattr(commands, "INTERACTIVE_COMMANDS", [])
    monkeypatch.setattr(commands, "NON_INTERACTIVE_COMMANDS", [])


def test_command_needs_tty_true_for_tty_program(_isolated_command_lists, monkeypatch):
    monkeypatch.setattr(commands, "INTERACTIVE_COMMANDS",
                        [{"command": "vim", "needs_tty": True}])
    assert commands.command_needs_tty("vim notes.txt") is True


def test_command_needs_tty_false_for_output_command(_isolated_command_lists, monkeypatch):
    monkeypatch.setattr(commands, "INTERACTIVE_COMMANDS",
                        [{"command": "git", "needs_tty": False}])
    assert commands.command_needs_tty("git status") is False


def test_command_needs_tty_defaults_false_when_flag_absent(_isolated_command_lists, monkeypatch):
    monkeypatch.setattr(commands, "NON_INTERACTIVE_COMMANDS",
                        [{"command": "ls"}])  # no needs_tty key
    assert commands.command_needs_tty("ls -la") is False


def test_command_needs_tty_false_for_unknown_command(_isolated_command_lists):
    assert commands.command_needs_tty("some_unlisted_thing --flag") is False


@pytest.mark.parametrize("cmd,expected", [
    # python: bare REPL needs a TTY; with a program it's output-style.
    ("python", True),
    ("python3", True),
    ("python script.py", False),
    ("python -c 'print(1)'", False),
    ("python -m http.server", False),
    ("python -i script.py", True),   # -i forces the REPL
    # crontab: -e edits in $EDITOR (TTY); -l/-r are output-style.
    ("crontab -e", True),
    ("crontab -l", False),
    # sh-family: bare shell is interactive; -c just runs a command.
    ("sh", True),
    ("sh -c 'echo hi'", False),
    ("bash -c 'ls'", False),
    ("zsh", True),
])
def test_command_needs_tty_argument_sensitive(_isolated_command_lists, cmd, expected):
    """Argument-dependent commands are decided by their args, NOT a flat JSON flag
    (and don't even need a list entry)."""
    assert commands.command_needs_tty(cmd) is expected


def test_command_lists_have_no_overlapping_commands():
    """Guard the dedup: a command name must live in exactly one list, else
    command_needs_tty / routing depend on list order rather than semantics."""
    import importlib.resources, json
    inter = json.loads(
        importlib.resources.files("monitor").joinpath("interactive_commands.json").read_text()
    )
    noninter = json.loads(
        importlib.resources.files("monitor").joinpath("non_interactive_commands.json").read_text()
    )
    ic = [e["command"] for e in inter]
    nc = [e["command"] for e in noninter]
    assert len(ic) == len(set(ic)), "duplicate command within interactive list"
    assert len(nc) == len(set(nc)), "duplicate command within non-interactive list"
    assert not (set(ic) & set(nc)), f"command(s) in both lists: {sorted(set(ic) & set(nc))}"


def test_execute_interactive_command_interactive_flag_follows_needs_tty(monkeypatch):
    """execute_interactive_command passes interactive=needs_tty to run_subprocess:
    True for a TTY program, False for an output-style command (so a front-end can
    capture it)."""
    monkeypatch.setattr(commands, "PRIVATE_COMMANDS", [])

    for entry, cmd, expected in (
        ({"command": "vim", "needs_tty": True}, "vim notes.txt", True),
        ({"command": "git", "needs_tty": False}, "git status", False),
    ):
        monkeypatch.setattr(commands, "INTERACTIVE_COMMANDS", [entry])
        captured = {}

        def fake_run(cmd_to_run, **kwargs):
            captured.update(kwargs)
            return (0, None, None, None)

        monkeypatch.setattr(commands, "run_subprocess", fake_run)
        commands.execute_interactive_command(cmd)
        assert captured.get("interactive") is expected, cmd


def test_real_interactive_json_carries_sane_needs_tty_flags():
    """Guard the actual shipped data: TTY programs flagged True, output tools False."""
    import importlib.resources, json
    data = json.loads(
        importlib.resources.files("monitor").joinpath("interactive_commands.json").read_text()
    )
    flags = {e["command"]: e.get("needs_tty") for e in data}
    # Every entry has an explicit boolean flag.
    assert all(isinstance(v, bool) for v in flags.values())
    # True TTY programs.
    for c in ("vim", "ssh", "top", "psql", "less"):
        assert flags.get(c) is True, c
    # Output-style tools that merely live in the interactive list.
    for c in ("git", "cat", "head", "git-log"):
        assert flags.get(c) is False, c
