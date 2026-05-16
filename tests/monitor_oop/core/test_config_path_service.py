"""Tests for config path resolution in Monitor OOP."""
from __future__ import annotations

import appdirs

from monitor_oop.core.config_path_context import ConfigPathContext
from monitor_oop.core.config_path_service import ConfigPathService


def test_get_user_config_dir_path_uses_app_name(monkeypatch, tmp_path) -> None:
    """Verify the user config directory is resolved from the application name."""

    expected_path = tmp_path / "monitor"
    monkeypatch.setattr(appdirs, "user_config_dir", lambda app_name: str(expected_path))

    service = ConfigPathService(app_name="monitor")

    assert service.get_user_config_dir_path() == str(expected_path)


def test_get_persistent_history_file_path_uses_config_context(monkeypatch, tmp_path) -> None:
    """Verify the history file path is built from the config context when values are omitted."""

    config_dir = tmp_path / "config"
    monkeypatch.setattr(appdirs, "user_config_dir", lambda app_name: str(config_dir))

    context = ConfigPathContext(history_dir="history", prompt_history_filename="prompt_history")
    service = ConfigPathService(context, app_name="monitor")

    result = service.get_persistent_history_file_path()

    assert result == str(config_dir / "history" / "prompt_history")


def test_get_system_prompt_file_path_falls_back_to_second_config_dir(monkeypatch, tmp_path) -> None:
    """Verify the system prompt path falls back to the next writable config directory."""

    first_dir = tmp_path / "primary"
    second_dir = tmp_path / "secondary"
    first_dir.mkdir()
    second_dir.mkdir()
    monkeypatch.setattr(appdirs, "user_config_dir", lambda app_name: str(first_dir))
    monkeypatch.setattr(
        "monitor_oop.core.config_path_service.os.path.expanduser",
        lambda path: str(second_dir),
    )
    monkeypatch.setattr(
        "monitor_oop.core.config_path_service.os.access",
        lambda path, mode: path != first_dir / "system_prompt" and path != first_dir,
    )

    service = ConfigPathService(app_name="monitor")

    result = service.get_system_prompt_file_path()

    assert result == str(second_dir / "system_prompt")


def test_get_log_file_path_uses_process_specific_filename(monkeypatch, tmp_path) -> None:
    """Verify the log file path includes the process id and log directory."""

    config_dir = tmp_path / "config"
    monkeypatch.setattr(appdirs, "user_config_dir", lambda app_name: str(config_dir))
    monkeypatch.setattr("monitor_oop.core.config_path_service.os.getpid", lambda: 12_345)

    service = ConfigPathService(app_name="monitor")

    result = service.get_log_file_path()

    assert result == str(config_dir / "log" / "monitor_12345.log")
