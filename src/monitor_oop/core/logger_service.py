"""Logging service for the isolated Monitor OOP application."""
from __future__ import annotations

import logging
from logging import Logger, getLogger
from os import getenv
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

    def configure(self, level: int | str | None = None, stream: TextIO | None = None) -> None:
        """Configure application-wide logging once.

        Args:
            level: Explicit logging level or level name to apply.
            stream: Optional stream to send log output to.
        """

        if self._configured:
            return
        logging.basicConfig(
            level=self._resolve_level(level),
            stream=stream,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
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
