"""Tests for LoggerService in the Monitor OOP core layer."""
from __future__ import annotations

import logging

from monitor_oop.core.logger_service import LoggerService


def test_configure_applies_explicit_integer_level_to_root_logger(tmp_path) -> None:
    """An explicit integer logging level should reach the root logger."""

    service = LoggerService()
    service.configure(level=10, log_file_path=str(tmp_path / "test.log"))

    assert logging.getLogger().level == 10


def test_configure_applies_level_name_to_root_logger(monkeypatch, tmp_path) -> None:
    """An explicit level name should be converted and applied to the root logger."""

    monkeypatch.delenv("LOG_LEVEL", raising=False)
    service = LoggerService()
    service.configure(level="warning", log_file_path=str(tmp_path / "test.log"))

    assert logging.getLogger().level == logging.WARNING


def test_configure_falls_back_to_environment_level(monkeypatch, tmp_path) -> None:
    """When no explicit level is provided, the environment LOG_LEVEL should apply."""

    monkeypatch.setenv("LOG_LEVEL", "error")
    service = LoggerService()
    service.configure(log_file_path=str(tmp_path / "test.log"))

    assert logging.getLogger().level == logging.ERROR
