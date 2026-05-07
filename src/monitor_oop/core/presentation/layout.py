"""Layout helpers for the Monitor OOP TUI."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TuiLayout:
    """Minimal three-pane layout description."""

    output_title: str = "Output"
    status_title: str = "Status Line"
    input_title: str = "Input"


def build_layout() -> TuiLayout:
    """Build the default three-pane TUI layout description."""

    return TuiLayout()
