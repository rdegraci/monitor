"""Tests for transcript viewport behavior."""
from __future__ import annotations

from monitor_oop.core.presentation.transcript_buffer import TranscriptBuffer, TranscriptEntry
from monitor_oop.core.presentation.transcript_renderer import TranscriptRenderer
from monitor_oop.core.presentation.transcript_viewport import TranscriptViewport


def test_follow_newest_tracks_appended_entries() -> None:
    """The viewport should follow newly appended transcript entries."""
    buffer = TranscriptBuffer()
    renderer = TranscriptRenderer()
    viewport = TranscriptViewport(buffer=buffer, renderer=renderer)

    buffer.append("user", "hello")
    viewport.note_appended_entry()

    assert viewport.follow_tail is True
    assert viewport.visible_end_index == 1
    assert viewport.visible_start_index == 0
    assert viewport.visible_text() == "> hello"

    buffer.append("assistant", "echo hi")
    viewport.note_appended_entry()

    assert viewport.follow_tail is True
    assert viewport.visible_end_index == 2
    assert viewport.visible_start_index == 0
    assert viewport.visible_text() == "> hello\nSTX\necho hi\n\nETX"


def test_manual_scroll_preserves_visible_window() -> None:
    """Scrolling should freeze the viewport window until tail-follow resumes."""
    buffer = TranscriptBuffer()
    renderer = TranscriptRenderer()
    viewport = TranscriptViewport(buffer=buffer, renderer=renderer)

    for index in range(5):
        buffer.append("user", f"line {index}")
    viewport.note_appended_entry()
    viewport.scroll_up(viewport_size=2)

    assert viewport.follow_tail is False
    assert viewport.visible_end_index == 2
    assert viewport.visible_start_index == 0
    assert viewport.visible_text() == "> line 0\n> line 1"

    buffer.append("user", "line 5")
    viewport.note_appended_entry()

    assert viewport.follow_tail is False
    assert viewport.visible_start_index == 0
    assert viewport.visible_end_index == 2
    assert viewport.visible_text() == "> line 0\n> line 1"


def test_scroll_bounds_clamp_to_available_entries() -> None:
    """Scrolling should stay within the available transcript bounds."""
    buffer = TranscriptBuffer()
    renderer = TranscriptRenderer()
    viewport = TranscriptViewport(buffer=buffer, renderer=renderer)

    for index in range(3):
        buffer.append("user", f"line {index}")
    viewport.follow_newest(viewport_size=2)

    viewport.scroll_up(viewport_size=2)
    viewport.scroll_up(viewport_size=2)
    viewport.scroll_up(viewport_size=2)

    assert viewport.visible_start_index == 0
    assert viewport.visible_end_index == 2
    assert viewport.visible_text() == "> line 0\n> line 1"

    viewport.scroll_down(viewport_size=2)
    assert viewport.visible_start_index == 1
    assert viewport.visible_end_index == 3
    assert viewport.follow_tail is True


def test_renderer_line_count_matches_rendered_output() -> None:
    """Renderer line counts should match the plain-text transcript output."""
    renderer = TranscriptRenderer()
    entries = [
        TranscriptEntry(role="user", text="hello"),
        TranscriptEntry(role="error", text="oops"),
    ]

    assert renderer.line_count(entries) == 2
    assert renderer.render_text(entries) == "> hello\nERROR: oops"
