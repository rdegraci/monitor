"""Tests for LoggerService in the Monitor OOP core layer."""
from __future__ import annotations

import logging

from monitor_oop.core.logger_service import LoggerService


def test_resolve_effective_level_uses_explicit_integer() -> None:
    """Verify an explicit integer logging level wins over environment defaults."""

    service = LoggerService()

    assert service._resolve_level(10) == 10


def test_resolve_effective_level_uses_level_name(monkeypatch) -> None:
    """Verify an explicit level name is converted to a logging level."""

    service = LoggerService()
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    assert service._resolve_level("warning") == logging.WARNING


def test_resolve_effective_level_falls_back_to_environment(monkeypatch) -> None:
    """Verify the environment level is used when no explicit level is provided."""

    service = LoggerService()
    monkeypatch.setenv("LOG_LEVEL", "error")

    assert service._resolve_level() == logging.ERROR


def test_prepare_log_path_defaults_to_application_log() -> None:
    """Verify the default log path is created under the logs directory."""

    service = LoggerService()

    assert str(service._prepare_log_path(None)) == "logs/application.log"
