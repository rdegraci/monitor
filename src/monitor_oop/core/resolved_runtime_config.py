"""Resolved runtime configuration for Monitor OOP."""
from __future__ import annotations

from dataclasses import dataclass

from monitor_oop.core.models import RuntimeConfig


def _normalize_runtime_config(config: RuntimeConfig) -> RuntimeConfig:
    """Hook for future runtime configuration normalization or validation."""
    return config


@dataclass(slots=True)
class ResolvedRuntimeConfig:
    """Fully resolved runtime configuration values."""

    config: RuntimeConfig
    logging_level: int
    openai_api_key: str | None
