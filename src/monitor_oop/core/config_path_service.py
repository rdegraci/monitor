"""Workspace path resolution for Monitor OOP."""
from __future__ import annotations

import os
from pathlib import Path

import appdirs

from monitor_oop.core.config_path_context import ConfigPathContext


class ConfigPathService:
    """Resolve user-writable configuration paths for the runtime."""

    def __init__(self, config: ConfigPathContext | None = None, app_name: str = "monitor") -> None:
        """Initialize the path service.

        Args:
            config: Optional runtime config with history path settings.
            app_name: Application name used for user config lookup.
        """

        self._config = config
        self._app_name = app_name

    def get_persistent_history_file_path(self, history_dir: str = "", filename: str = "") -> str:
        """Return the first writable persistent history file path.

        Args:
            history_dir: Relative history directory under the config root.
            filename: History filename to use when present.

        Returns:
            A writable file path, or an empty string if none is available.
        """

        if not history_dir and self._config is not None:
            history_dir = self._config.history_dir
        if not filename and self._config is not None:
            filename = self._config.prompt_history_filename

        for candidate in self._candidate_config_dirs():
            writable_path = self._build_history_file_path(candidate, history_dir, filename)
            if writable_path:
                return writable_path

        return ""

    def get_system_prompt_file_path(self) -> str:
        """Return the first writable system prompt file path."""

        for candidate in self._candidate_config_dirs():
            writable_path = self._build_system_prompt_file_path(candidate)
            if writable_path:
                return writable_path

        return ""

    def get_log_file_path(self) -> str:
        """Return the first writable per-process log file path."""

        for candidate in self._candidate_config_dirs():
            writable_path = self._build_log_file_path(candidate)
            if writable_path:
                return writable_path

        return ""

    def _candidate_config_dirs(self) -> list[Path]:
        """Return candidate configuration directories in lookup order."""

        return [
            Path(appdirs.user_config_dir(self._app_name)),
            Path(os.path.expanduser("~/.config/monitor")),
        ]

    def _ensure_writable_dir(self, path: Path) -> bool:
        """Ensure a directory exists and is writable.

        Args:
            path: Directory path to validate.

        Returns:
            True when the directory exists and is writable.
        """

        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False

        return os.access(path, os.W_OK)

    def _build_history_file_path(self, base_dir: Path, history_dir: str, filename: str) -> str:
        """Build a writable prompt history file path.

        Args:
            base_dir: Base directory to resolve under.
            history_dir: History subdirectory.
            filename: History filename.

        Returns:
            A writable file path, or an empty string if unavailable.
        """

        history_path = base_dir / history_dir / (filename or "prompt_history")
        if not self._ensure_writable_dir(history_path.parent):
            return ""

        return str(history_path)

    def _build_system_prompt_file_path(self, base_dir: Path) -> str:
        """Build a writable system prompt file path.

        Args:
            base_dir: Base directory to resolve under.

        Returns:
            A writable file path, or an empty string if unavailable.
        """

        system_prompt_path = base_dir / "system_prompt"
        if not self._ensure_writable_dir(system_prompt_path.parent):
            return ""

        return str(system_prompt_path)

    def _build_log_file_path(self, base_dir: Path) -> str:
        """Build a writable log file path.

        Args:
            base_dir: Base directory to resolve under.

        Returns:
            A writable file path, or an empty string if unavailable.
        """

        log_file_path = base_dir / "log" / f"monitor_{os.getpid()}.log"
        if not self._ensure_writable_dir(log_file_path.parent):
            return ""

        return str(log_file_path)
