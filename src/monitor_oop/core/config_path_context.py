"""Runtime config path contract for Monitor OOP."""
from __future__ import annotations

from dataclasses import dataclass


def _normalize_path_component(value: str) -> str:
    return value


@dataclass(slots=True)
class ConfigPathContext:
    """Minimum path configuration required by ConfigPathService."""

    history_dir: str
    prompt_history_filename: str
