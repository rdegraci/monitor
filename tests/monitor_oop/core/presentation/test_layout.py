"""Tests for TUI layout helpers."""
from monitor_oop.core.presentation.layout import TuiLayout
from monitor_oop.core.presentation.layout import build_layout


def test_build_layout_returns_default_titles() -> None:
    """Verify the default layout uses the expected pane titles."""

    layout = build_layout()

    assert isinstance(layout, TuiLayout)
    assert layout.output_title == "Output"
    assert layout.status_title == "Status Line"
    assert layout.input_title == "Input"
