"""Logging service for the isolated Monitor OOP application."""
from __future__ import annotations

import logging
import sys
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

    def _build_stream_handler(self, stream: TextIO | None = None) -> StreamHandler:
        """Create a stream handler for application bootstrap logging.

        Args:
            stream: Optional stream to send log output to.

        Returns:
            A configured stream handler.
        """

        return StreamHandler(stream if stream is not None else sys.stderr)

    def _bootstrap_failure(self, message: str, exc: BaseException) -> None:
        """Report a bootstrap failure to stderr before raising it.

        Args:
            message: The failure message to report.
            exc: The exception that triggered the failure.
        """

        failure_handler = self._build_stream_handler(sys.stderr)
        failure_handler.setLevel(logging.CRITICAL)
        failure_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

        failure_logger = logging.getLogger(__name__)
        failure_logger.handlers = [failure_handler]
        failure_logger.setLevel(logging.CRITICAL)
        failure_logger.propagate = False
        failure_logger.critical("%s", message, exc_info=exc)

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
        existing_handlers = list(root_logger.handlers)

        handlers: list[logging.Handler] = []

        try:
            resolved_level = self._resolve_level(level)
            formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

            if log_file_path is not None:
                log_path = Path(log_file_path).expanduser()
                log_path.parent.mkdir(parents=True, exist_ok=True)

                file_handler = FileHandler(log_path)
                file_handler.setLevel(logging.DEBUG)
                file_handler.setFormatter(formatter)
                handlers.append(file_handler)

                if stream_output:
                    stream_handler = self._build_stream_handler(stream if stream is not None else sys.stderr)
                    stream_handler.setLevel(logging.WARNING)
                    stream_handler.setFormatter(formatter)
                    handlers.append(stream_handler)
            elif stream_output:
                stream_handler = self._build_stream_handler(stream if stream is not None else sys.stderr)
                stream_handler.setLevel(logging.WARNING)
                stream_handler.setFormatter(formatter)
                handlers.append(stream_handler)

            for handler in existing_handlers:
                root_logger.removeHandler(handler)
                handler.close()

            for handler in handlers:
                root_logger.addHandler(handler)

            root_logger.setLevel(resolved_level)
            self._configured = True
        except Exception as exc:
            self._bootstrap_failure("Logging configuration failed.", exc)
            raise

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
