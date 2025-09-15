import pytest
from unittest import mock
from monitor.lib import terminal_commands

def test_is_executable_on_path_true_false(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda exe: "/bin/ls" if exe == "ls" else None)
    assert terminal_commands.is_executable_on_path("ls") is True
    assert terminal_commands.is_executable_on_path("not-an-exe") is False

def test_is_platform_mac(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    assert terminal_commands.is_platform_mac() is True
    monkeypatch.setattr("platform.system", lambda: "Linux")
    assert terminal_commands.is_platform_mac() is False

def test_is_platform_unix(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    assert terminal_commands.is_platform_unix() is True
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    assert terminal_commands.is_platform_unix() is True
    monkeypatch.setattr("platform.system", lambda: "Windows")
    assert terminal_commands.is_platform_unix() is False

def test_run_command_in_terminal_not_mac(monkeypatch, caplog):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    with caplog.at_level("ERROR"):
        terminal_commands.run_command_in_terminal("echo hello")
    assert "run_command_in_terminal is only supported on macOS." in caplog.text

def test_run_command_in_terminal_no_osascript(monkeypatch, caplog):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("shutil.which", lambda exe: None)
    with caplog.at_level("ERROR"):
        terminal_commands.run_command_in_terminal("echo hello")
    assert "'osascript' is not available" in caplog.text

def test_run_command_in_terminal_applescript_failure(monkeypatch, caplog):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("shutil.which", lambda exe: "path/to/osascript")
    mock_run = mock.Mock()
    mock_run.return_value = mock.Mock(returncode=1, stderr="fail", stdout="")
    monkeypatch.setattr("subprocess.run", mock_run)
    with caplog.at_level("ERROR"):
        terminal_commands.run_command_in_terminal("echo hello")
    assert "AppleScript (osascript) command failed" in caplog.text

def test_run_command_in_terminal_success(monkeypatch, caplog):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("shutil.which", lambda exe: "path/to/osascript")
    mock_run = mock.Mock()
    mock_run.return_value = mock.Mock(returncode=0, stderr="", stdout="ok")
    monkeypatch.setattr("subprocess.run", mock_run)
    with caplog.at_level("INFO"):
        terminal_commands.run_command_in_terminal("echo hello")
    assert "Successfully ran AppleScript" in caplog.text

def test_run_command_in_terminal_exception(monkeypatch, caplog):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("shutil.which", lambda exe: "path/to/osascript")
    def raise_exception(*a, **k):
        raise RuntimeError("fail")
    monkeypatch.setattr("subprocess.run", raise_exception)
    with caplog.at_level("ERROR"):
        terminal_commands.run_command_in_terminal("echo hello")
    assert "Exception while executing AppleScript" in caplog.text

def test_run_command_in_screen_not_unix(monkeypatch, caplog):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    with caplog.at_level("ERROR"):
        terminal_commands.run_command_in_screen("ls")
    assert "run_command_in_screen is only supported on UNIX-like systems" in caplog.text

def test_run_command_in_screen_no_screen(monkeypatch, caplog):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("shutil.which", lambda exe: None)
    with caplog.at_level("ERROR"):
        terminal_commands.run_command_in_screen("ls")
    assert "screen' is not installed or not found in PATH" in caplog.text

def test_run_command_in_screen_session_failure(monkeypatch, caplog):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("shutil.which", lambda exe: "path/to/screen")
    mock_run = mock.Mock()
    failure = mock.Mock(returncode=1, stderr="fail", stdout="")
    mock_run.side_effect = [failure]
    monkeypatch.setattr("subprocess.run", mock_run)
    with caplog.at_level("ERROR"):
        terminal_commands.run_command_in_screen("ls")
    assert "Failed to create screen session" in caplog.text

def test_run_command_in_screen_stuff_failure(monkeypatch, caplog):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("shutil.which", lambda exe: "path/to/screen")
    mock_run = mock.Mock()
    success = mock.Mock(returncode=0, stderr="", stdout="")
    failure = mock.Mock(returncode=1, stderr="failx", stdout="")
    mock_run.side_effect = [success, failure]
    monkeypatch.setattr("subprocess.run", mock_run)
    with caplog.at_level("ERROR"):
        terminal_commands.run_command_in_screen("ls")
    assert "Failed to send command to screen session" in caplog.text

def test_run_command_in_screen_success(monkeypatch, caplog):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("shutil.which", lambda exe: "path/to/screen")
    mock_run = mock.Mock()
    success = mock.Mock(returncode=0, stderr="", stdout="")
    mock_run.side_effect = [success, success]
    monkeypatch.setattr("subprocess.run", mock_run)
    with caplog.at_level("INFO"):
        terminal_commands.run_command_in_screen("ls", session_name="foobar")
    assert "Command 'ls' is running in screen session 'foobar'" in caplog.text

def test_run_command_in_screen_exception(monkeypatch, caplog):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("shutil.which", lambda exe: "path/to/screen")
    def raise_exception(*a, **k):
        raise RuntimeError("failz")
    monkeypatch.setattr("subprocess.run", raise_exception)
    with caplog.at_level("ERROR"):
        terminal_commands.run_command_in_screen("ls")
    assert "Exception while trying to launch command in screen session" in caplog.text
