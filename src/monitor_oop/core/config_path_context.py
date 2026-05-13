"""Runtime config path contract for Monitor OOP."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ConfigPathContext:
    """Minimum path configuration required by ConfigPathService."""

    history_dir: str
    prompt_history_filename: str
