"""Logging service for the isolated Monitor OOP application."""
from __future__ import annotations

import logging
from logging import Logger, getLogger
from typing import TextIO


class LoggerService:
    """Own application-wide logging configuration and logger access."""

    def __init__(self) -> None:
        self._configured = False

    def configure(self, level: int = logging.INFO, stream: TextIO | None = None) -> None:
        """Configure application-wide logging once.

        Args:
            level: The logging level to apply.
            stream: Optional stream to send log output to.
        """

        if self._configured:
            return
        logging.basicConfig(
            level=level,
            stream=stream,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        self._configured = True

    def get_logger(self, name: str) -> Logger:
        """Return a standard library logger for a module or component."""

        return getLogger(name)
