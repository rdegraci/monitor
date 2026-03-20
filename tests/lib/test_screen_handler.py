import json
import subprocess
from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest

from monitor.lib.screen_handler import ScreenHandler, ScreenHandlerError


@pytest.fixture
def handler(tmp_path, monkeypatch):
    # Use temp dirs for logs/meta
    log_dir = tmp_path / "logs"
    meta_dir = tmp_path / "meta"
    handler = ScreenHandler(monitor_cmd=["/usr/bin/python", "-m", "monitor"], base_log_dir=str(log_dir), base_meta_dir=str(meta_dir))

    # Mock shutil.which to return a fake path for 'screen'
    monkeypatch.setattr("monitor.lib.screen_handler.shutil_which", lambda exe: "/usr/bin/screen")
    return handler


def test_generate_session_name_format(handler):
    name = handler.generate_session_name()
    assert len(name.split("_")) == 2
    datepart, suffix = name.split("_")
    assert len(datepart) == 8
    assert len(suffix) == 3


@patch("subprocess.run")
def test_create_interactive_subagent_runs_screen_and_stuffs(mock_run, handler, tmp_path):
    # Simulate successful creation (screen -dm) then successful stuff
    # First call: screen -S name -dm <monitor_cmd>
    # Subsequent calls: screen -S name -p 0 -X stuff <prompt>
    mock_cp = MagicMock()
    mock_cp.returncode = 0
    mock_run.return_value = mock_cp

    prompt = "Hello sub-agent"
    info = handler.create_interactive_subagent(prompt)
    assert "session_name" in info
    assert Path(info["meta_path"]).exists()

    # Verify that subprocess.run was called at least twice (create + stuff attempts)
    assert mock_run.call_count >= 2


@patch("subprocess.run")
def test_send_to_session_calls_stuff(mock_run, handler):
    mock_cp = MagicMock()
    mock_cp.returncode = 0
    mock_run.return_value = mock_cp

    ok = handler.send_to_session("20261003_abc", "do something")
    assert ok is True
    mock_run.assert_called()


@patch("subprocess.run")
def test_list_sessions_parsing(mock_run, handler):
    sample = "\t1234.sessone\t(Detached)\n\t2345.sesstwo\t(Attached)\n"
    mock_cp = MagicMock()
    mock_cp.stdout = sample
    mock_run.return_value = mock_cp

    sessions = handler.list_sessions()
    names = [s["name"] for s in sessions]
    assert "sessone" in names
    assert "sesstwo" in names


@patch("subprocess.run")
def test_kill_session_invokes_screen_quit(mock_run, handler):
    mock_cp = MagicMock()
    mock_cp.returncode = 0
    mock_run.return_value = mock_cp

    ok = handler.kill_session("20261003_abc")
    assert ok is True
    mock_run.assert_called()
