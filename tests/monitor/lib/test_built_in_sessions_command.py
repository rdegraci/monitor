from pathlib import Path
from unittest.mock import patch

import monitor.lib.built_in_commands as bic


def test_sessions_command_prints_five_most_recent_paths(capsys):
    """Verify :sessions prints the five most recent session folder paths."""
    with patch(
        "monitor.lib.built_in_commands.get_sessions_root",
        return_value=Path("/tmp/monitor/sessions"),
    ), patch(
        "monitor.lib.built_in_commands.list_most_recent_session_folders",
        return_value=[
            Path("/tmp/monitor/sessions/5"),
            Path("/tmp/monitor/sessions/4"),
            Path("/tmp/monitor/sessions/3"),
            Path("/tmp/monitor/sessions/2"),
            Path("/tmp/monitor/sessions/1"),
        ],
    ) as mock_list:
        bic.sessions_command("")

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        str(Path("/tmp/monitor/sessions/5").resolve()),
        str(Path("/tmp/monitor/sessions/4").resolve()),
        str(Path("/tmp/monitor/sessions/3").resolve()),
        str(Path("/tmp/monitor/sessions/2").resolve()),
        str(Path("/tmp/monitor/sessions/1").resolve()),
    ]
    mock_list.assert_called_once_with(limit=5)


def test_sessions_command_reports_empty_root(capsys):
    """Verify :sessions prints a helpful message when no sessions exist."""
    with patch(
        "monitor.lib.built_in_commands.get_sessions_root",
        return_value=Path("/tmp/monitor/sessions"),
    ), patch(
        "monitor.lib.built_in_commands.list_most_recent_session_folders",
        return_value=[],
    ) as mock_list:
        bic.sessions_command("")

    captured = capsys.readouterr()
    assert "No session folders found under /tmp/monitor/sessions" in captured.out
    mock_list.assert_called_once_with(limit=5)
