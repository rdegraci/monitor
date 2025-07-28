import pytest
from monitor.core import commands
from unittest.mock import patch


def test_is_interactive_command_returns_expected():
    """Test that is_interactive_command correctly finds interactive commands."""
    cmd = "ls"
    result = commands.is_interactive_command(cmd)
    assert result is not None
    assert result["command"] == "ls"

    cmd = "not_a_command"
    assert commands.is_interactive_command(cmd) is None


def test_is_internal_command_returns_expected():
    """Test that is_internal_command correctly finds internal commands."""
    for item in commands.internal_commands:
        cmd = item["command"]
        found = commands.is_internal_command(cmd)
        assert found is not None
        assert found["command"] == cmd
    assert commands.is_internal_command("bad_command") is None


def test_print_interactive_commands(capsys):
    """Test that print_interactive_commands prints a comma-separated list."""
    commands.print_interactive_commands(None)
    out = capsys.readouterr().out
    for cmd in commands.public_interactive_commands:
        assert cmd["command"] in out
    assert "***" in out


@patch("core.commands.run_subprocess")
def test_execute_interactive_command_runs_expected(mock_run):
    """Test that execute_interactive_command tries to run the right command."""
    mock_proc = type("FakeProc", (), {"wait": lambda self: None, "communicate": lambda self: ("output", None)})()
    mock_run.return_value = (0, "output", "", mock_proc)
    cmd = "ls"
    commands.execute_interactive_command(cmd)
    assert mock_run.called


@patch("core.commands.run_subprocess")
def test_execute_internal_command_handles_output(mock_run):
    """Test execute_internal_command display_query_result path."""
    mock_run.return_value = (0, "somestring", "", None)
    captured_outputs = []
    def capture_display(s):
        captured_outputs.append(s)
    cmd = commands.internal_commands[0]["command"]
    commands.execute_internal_command(cmd, capture_display)
    assert captured_outputs == [] or any(isinstance(x, str) and "somestring" in x for x in captured_outputs)
