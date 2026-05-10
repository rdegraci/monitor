"""Logging service for the isolated Monitor OOP application."""
from __future__ import annotations

import logging
from logging import FileHandler, Logger, StreamHandler, getLogger
from os import getenv
from pathlib import Path
from typing import TextIO


class LoggerService:
    """Own application-wide logging configuration and logger access."""

    def __init__(self) -> None:
        self._configured = False

    def _resolve_level(self, level: int | str | None = None) -> int:
        """Resolve the effective logging level.

        Args:
            level: Explicit logging level as an integer, level name, or None.

        Returns:
            The resolved logging level as an integer.
        """

        if isinstance(level, int):
            return level
        if isinstance(level, str):
            resolved = logging.getLevelName(level.upper())
            if isinstance(resolved, int):
                return resolved
        env_level = getenv("LOG_LEVEL")
        if env_level:
            resolved = logging.getLevelName(env_level.upper())
            if isinstance(resolved, int):
                return resolved
        return logging.INFO

    def _build_logger_directory(self, log_file_path: str | Path) -> Path:
        """Build the directory path for a log file.

        Args:
            log_file_path: File path used for logging output.

        Returns:
            The parent directory for the provided log file path.
        """

        return self._log_file_parent_directory(log_file_path)

    def _log_file_parent_directory(self, log_file_path: str | Path) -> Path:
        """Return the parent directory for a writable log file path."""

        return Path(log_file_path).expanduser().parent

    def configure(
        self,
        level: int | str | None = None,
        log_file_path: str | Path | None = None,
        stream: TextIO | None = None,
        stream_output: bool = False,
    ) -> None:
        """Configure application-wide logging once.

        Args:
            level: Explicit logging level or level name to apply.
            log_file_path: Optional file path for log output.
            stream: Optional stream to send log output to.
            stream_output: Whether to attach a stream handler when stream is provided.
        """

        if self._configured:
            return

        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()

        handlers: list[logging.Handler] = []

        if log_file_path is not None:
            log_path = Path(log_file_path).expanduser()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(FileHandler(log_path))

        if stream_output and stream is not None:
            handlers.append(StreamHandler(stream))

        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        for handler in handlers:
            handler.setLevel(self._resolve_level(level))
            handler.setFormatter(formatter)
            root_logger.addHandler(handler)

        root_logger.setLevel(self._resolve_level(level))
        self._configured = True

    def get_logger(self, name: str) -> Logger:
        """Return a standard library logger for a module or component."""

        return getLogger(name)

    def get_module_logger(self, module: str) -> Logger:
        """Return a logger scoped to a module name.

        Args:
            module: The module name to use for logger access.

        Returns:
            A standard library logger for the requested module.
        """

        return self.get_logger(module)
