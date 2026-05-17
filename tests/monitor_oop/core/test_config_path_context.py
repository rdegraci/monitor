"""Tests for ConfigPathContext in the Monitor OOP core layer."""
from __future__ import annotations

from monitor_oop.core.config_path_context import ConfigPathContext


def test_config_path_context_stores_path_components() -> None:
    """Verify the dataclass stores the provided path components unchanged."""

    context = ConfigPathContext(history_dir="history", prompt_history_filename="prompt_history")

    assert context.history_dir == "history"
    assert context.prompt_history_filename == "prompt_history"
