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

def test_run_command_in_screen_unknown_subcommand_shows_usage(capsys):
    # The legacy `:agent <text>` fallthrough-spawn was removed (it bypassed the
    # orchestration gate + caps and turned typos into stray sessions). An
    # unrecognized subcommand must now show usage and spawn NOTHING.
    terminal_commands.run_command_in_screen("doit")
    out = capsys.readouterr().out
    assert "Unknown :agent subcommand" in out
    assert "Usage: : (or /) agent" in out  # usage block follows

def test_attach_resolves_token(monkeypatch, caplog):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("shutil.which", lambda exe: "path/to/screen")
    # resolve_screen_token returns a resolved token
    # resolve_screen_token now lives in monitor.lib.agent.attach (the
    # attach handler imports it at module load); patch there so the
    # bound name inside the handler is replaced.
    from monitor.lib.agent import attach as _attach_mod
    monkeypatch.setattr(_attach_mod, "resolve_screen_token", lambda screen_cmd, session_name: "37082.20260323_fih")
    mock_run = mock.Mock()
    mock_run.return_value = mock.Mock(returncode=0, stderr="", stdout="")
    monkeypatch.setattr("subprocess.run", mock_run)
    with caplog.at_level("INFO"):
        terminal_commands.run_command_in_screen("attach 20260323_fih")
    # Ensure subprocess.run was called with the resolved token
    assert mock_run.call_count >= 1
    called_lists = [c[0][0] for c in mock_run.call_args_list if len(c[0]) > 0]
    assert ["screen", "-r", "37082.20260323_fih"] in called_lists
    # Ensure log contains info about attaching to that token
    assert "37082.20260323_fih" in caplog.text
    assert "attach" in caplog.text.lower()

def test_attach_fallback_no_resolution(monkeypatch, caplog):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("shutil.which", lambda exe: "path/to/screen")
    # resolve_screen_token returns None, so fallback to provided token
    # resolve_screen_token now lives in monitor.lib.agent.attach — patch
    # there so the bound name inside the handler returns None and we
    # exercise the fallback-to-raw-token path.
    from monitor.lib.agent import attach as _attach_mod
    monkeypatch.setattr(_attach_mod, "resolve_screen_token", lambda screen_cmd, session_name: None)
    mock_run = mock.Mock()
    mock_run.return_value = mock.Mock(returncode=1, stderr="fail", stdout="")
    monkeypatch.setattr("subprocess.run", mock_run)
    with caplog.at_level("ERROR"):
        terminal_commands.run_command_in_screen("attach 20260323_fih")
    # Ensure subprocess.run was called with the original token when resolution failed
    assert mock_run.call_count >= 1
    called_lists = [c[0][0] for c in mock_run.call_args_list if len(c[0]) > 0]
    assert ["screen", "-r", "20260323_fih"] in called_lists
    # Ensure log contains the error message indicating failure to attach
    assert "Failed to attach to screen session" in caplog.text

def test_list_indexed_sessions_full(monkeypatch, capsys):
    # Ensure environment looks like UNIX with screen installed
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("shutil.which", lambda exe: "path/to/screen")
    # Prepare full entries
    full_entries = [
        {
            "index": 0,
            "name": "session-alpha",
            "token": "1001.alpha",
            "state": "attached",
            "created": "2026-03-23T10:00:00Z",
            "meta": "/tmp/meta-alpha"
        },
        {
            "index": 1,
            "name": "session-beta",
            "token": "1002.beta",
            "state": "detached",
            "created": "2026-03-23T11:00:00Z",
            "meta": "/tmp/meta-beta"
        }
    ]
    # Monkeypatch the screen handler to return the full entries when requested
    monkeypatch.setattr(terminal_commands._SCREEN_HANDLER, "list_indexed_sessions", lambda full: full_entries)
    # Set instance_id and sessions_file on the handler for header/footer info
    monkeypatch.setattr(terminal_commands._SCREEN_HANDLER, "instance_id", "instance-123")
    monkeypatch.setattr(terminal_commands._SCREEN_HANDLER, "sessions_file", "/var/lib/app/sessions.db")
    # Run the list --full command and capture stdout
    terminal_commands.run_command_in_screen("list --full")
    captured = capsys.readouterr()
    out = captured.out
    # Assertions: instance id and sessions file basename
    assert "instance-123" in out
    assert "sessions.db" in out
    # Headers should include these columns
    assert "Index" in out
    assert "Name" in out
    assert "Token" in out
    assert "State" in out
    assert "Created" in out
    assert "Meta" in out
    # Ensure the two sessions and their tokens are present
    assert "session-alpha" in out
    assert "1001.alpha" in out
    assert "session-beta" in out
    assert "1002.beta" in out

def test_list_indexed_sessions_compact(monkeypatch, capsys):
    # Ensure environment looks like UNIX with screen installed
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("shutil.which", lambda exe: "path/to/screen")
    # Prepare compact entries
    compact_entries = [
        {
            "index": 0,
            "name": "compact-one",
            "state": "running",
            "created": "2026-03-23T09:00:00Z"
        },
        {
            "index": 1,
            "name": "compact-two",
            "state": "stopped",
            "created": "2026-03-23T09:30:00Z"
        }
    ]
    # Monkeypatch the screen handler to return compact entries when full=False
    monkeypatch.setattr(terminal_commands._SCREEN_HANDLER, "list_indexed_sessions", lambda full: compact_entries)
    # Run the compact list command and capture stdout
    terminal_commands.run_command_in_screen("list")
    captured = capsys.readouterr()
    out = captured.out
    # Headers for compact mode
    assert "Index" in out
    assert "Name" in out
    assert "State" in out
    assert "Created" in out
    # Ensure the session names are present
    assert "compact-one" in out
    assert "compact-two" in out
