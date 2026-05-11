"""Transcript viewport state for the Monitor OOP TUI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Sequence, TypeVar

if TYPE_CHECKING:
    from .transcript_buffer import TranscriptBuffer
    from .transcript_renderer import TranscriptRenderer

T = TypeVar("T")


@dataclass(slots=True, init=False)
class TranscriptViewport:
    """Own the visible transcript window and follow-tail behavior."""

    buffer: TranscriptBuffer | None = field(default=None, repr=False)
    renderer: TranscriptRenderer | None = field(default=None, repr=False)
    visible_start_index: int = 0
    visible_end_index: int = 0
    follow_tail: bool = True
    default_viewport_size: int = 1

    def __init__(
        self,
        buffer: TranscriptBuffer | None = None,
        renderer: TranscriptRenderer | None = None,
        visible_start_index: int = 0,
        visible_end_index: int = 0,
        follow_tail: bool = True,
        default_viewport_size: int = 1,
    ) -> None:
        """Initialize the transcript viewport.

        Args:
            buffer: Transcript buffer to own.
            renderer: Transcript renderer to own.
            visible_start_index: Starting index of the visible range.
            visible_end_index: Ending index of the visible range.
            follow_tail: Whether the viewport should follow the transcript tail.
            default_viewport_size: Fallback viewport size.
        """
        self.buffer = buffer
        self.renderer = renderer
        self.visible_start_index = visible_start_index
        self.visible_end_index = visible_end_index
        self.follow_tail = follow_tail
        self.default_viewport_size = default_viewport_size

    def _resolve_active_entries(self) -> Sequence[T]:
        """Resolve the active transcript entries from the owned buffer.

        Returns:
            The active transcript entries, or an empty sequence if no buffer exists.
        """
        if self.buffer is None:
            return []
        return self.buffer.entries

    def _resolve_viewport_size(
        self,
        viewport_size: int | None = None,
        viewport_height: int | None = None,
    ) -> int:
        """Resolve and store the active viewport size.

        Args:
            viewport_size: Number of lines available in the viewport, if provided.
            viewport_height: Number of lines available in the viewport, if provided.

        Returns:
            The resolved viewport size, preferring the renderer line count when
            the provided size is omitted or non-positive.
        """
        resolved_viewport_size = viewport_height
        if resolved_viewport_size is None:
            resolved_viewport_size = viewport_size
        active_entries = self._resolve_active_entries()
        if resolved_viewport_size is None or resolved_viewport_size <= 0:
            if self.renderer is not None:
                rendered_line_count = self.renderer.line_count(active_entries)
                if rendered_line_count > 0:
                    resolved_viewport_size = rendered_line_count
        if resolved_viewport_size is None or resolved_viewport_size <= 0:
            resolved_viewport_size = self.default_viewport_size
        self.default_viewport_size = max(resolved_viewport_size, 1)
        return self.default_viewport_size

    def follow_newest(
        self,
        transcript_entries: Sequence[T] | None = None,
        viewport_size: int | None = None,
        viewport_height: int | None = None,
    ) -> None:
        """Move the viewport to the newest entries and keep tail-follow enabled.

        Args:
            transcript_entries: Transcript entries available for display. If omitted,
                the owned buffer entries are used.
            viewport_size: Number of lines available in the viewport.
            viewport_height: Number of lines available in the viewport.
        """
        if transcript_entries is None:
            transcript_entries = self._resolve_active_entries()
        self.jump_to_tail(transcript_entries, viewport_size, viewport_height)

    def note_appended_entry(
        self,
        transcript_entries: Sequence[T] | None = None,
        viewport_size: int | None = None,
        viewport_height: int | None = None,
    ) -> None:
        """Record that a new transcript entry was appended.

        If the viewport is currently following the tail, this preserves the tail
        position. Otherwise, the visible range is left intact.

        Args:
            transcript_entries: Transcript entries available for display. If omitted,
                the owned buffer entries are used.
            viewport_size: Number of lines available in the viewport.
            viewport_height: Number of lines available in the viewport.
        """
        if transcript_entries is None:
            transcript_entries = self._resolve_active_entries()
        if self.follow_tail:
            self.follow_newest(transcript_entries, viewport_size, viewport_height)
            return
        self.sync(transcript_entries, viewport_size, viewport_height)

    def sync(
        self,
        transcript_entries: Sequence[T],
        viewport_size: int | None = None,
        viewport_height: int | None = None,
    ) -> None:
        """Keep the viewport indices internally consistent.

        Args:
            transcript_entries: Transcript entries available for display.
            viewport_size: Number of lines available in the viewport.
            viewport_height: Number of lines available in the viewport.
        """
        viewport_size = self._resolve_viewport_size(viewport_size, viewport_height)
        entry_count = len(transcript_entries)
        if entry_count <= 0:
            self.visible_start_index = 0
            self.visible_end_index = 0
            self.follow_tail = True
            return
        if self.follow_tail:
            self.visible_end_index = entry_count
        self.visible_end_index = min(max(self.visible_end_index, 0), entry_count)
        visible_count = max(min(viewport_size, entry_count), 1)
        self.visible_start_index = max(self.visible_end_index - visible_count, 0)
        if self.visible_end_index >= entry_count:
            self.follow_tail = True

    def sync_from_buffer(self, viewport_size: int | None = None, viewport_height: int | None = None) -> None:
        """Keep the viewport indices consistent with the owned transcript buffer.

        Args:
            viewport_size: Number of lines available in the viewport.
            viewport_height: Number of lines available in the viewport.
        """
        active_viewport_size = self._resolve_viewport_size(viewport_size, viewport_height)
        self.sync(self._resolve_active_entries(), active_viewport_size)

    def scroll(
        self,
        transcript_entries: Sequence[T],
        offset: int,
        viewport_size: int | None = None,
        viewport_height: int | None = None,
    ) -> None:
        """Scroll the visible viewport by an offset.

        Args:
            transcript_entries: Transcript entries available for display.
            offset: Number of lines to move the viewport by.
            viewport_size: Number of lines available in the viewport.
            viewport_height: Number of lines available in the viewport.
        """
        viewport_size = self._resolve_viewport_size(viewport_size, viewport_height)
        entry_count = len(transcript_entries)
        if entry_count <= 0:
            self.sync(transcript_entries, viewport_size)
            return
        self.follow_tail = False
        visible_count = max(min(viewport_size, entry_count), 1)
        max_start = max(entry_count - visible_count, 0)
        new_start = min(max(self.visible_start_index + offset, 0), max_start)
        self.visible_start_index = new_start
        self.visible_end_index = min(new_start + visible_count, entry_count)
        if self.visible_end_index >= entry_count:
            self.follow_tail = True

    def scroll_up(self, viewport_size: int | None = None, viewport_height: int | None = None) -> None:
        """Scroll the visible viewport up by one line.

        Args:
            viewport_size: Number of lines available in the viewport.
            viewport_height: Number of lines available in the viewport.
        """
        active_viewport_size = self._resolve_viewport_size(viewport_size, viewport_height)
        if self.buffer is None:
            self.scroll([], -1, active_viewport_size)
            return
        self.scroll(self.buffer.entries, -1, active_viewport_size)

    def scroll_down(self, viewport_size: int | None = None, viewport_height: int | None = None) -> None:
        """Scroll the visible viewport down by one line.

        Args:
            viewport_size: Number of lines available in the viewport.
            viewport_height: Number of lines available in the viewport.
        """
        active_viewport_size = self._resolve_viewport_size(viewport_size, viewport_height)
        if self.buffer is None:
            self.scroll([], 1, active_viewport_size)
            return
        self.scroll(self.buffer.entries, 1, active_viewport_size)

    def jump_to_tail(
        self,
        transcript_entries: Sequence[T],
        viewport_size: int | None = None,
        viewport_height: int | None = None,
    ) -> None:
        """Jump the visible viewport to the newest transcript entries.

        Args:
            transcript_entries: Transcript entries available for display.
            viewport_size: Number of lines available in the viewport.
            viewport_height: Number of lines available in the viewport.
        """
        viewport_size = self._resolve_viewport_size(viewport_size, viewport_height)
        entry_count = len(transcript_entries)
        if entry_count <= 0:
            self.sync(transcript_entries, viewport_size)
            return
        visible_count = max(min(viewport_size, entry_count), 1)
        self.visible_end_index = entry_count
        self.visible_start_index = max(entry_count - visible_count, 0)
        self.follow_tail = True

    def _visible_text_from_entries(
        self,
        transcript_entries: Sequence[T],
        viewport_size: int | None = None,
        viewport_height: int | None = None,
    ) -> str:
        """Return rendered text for the visible transcript entries."""
        viewport_size = self._resolve_viewport_size(viewport_size, viewport_height)
        if self.follow_tail:
            self.sync(transcript_entries, viewport_size, viewport_height)
        entries = transcript_entries[
            self.visible_start_index : self.visible_end_index
        ]
        if self.renderer is None:
            return ""
        return self.renderer.format(entries)

    def get_formatted_text(self, viewport_size: int | None = None, viewport_height: int | None = None) -> str:
        """Return the visible transcript as formatted text for the output pane.

        Args:
            viewport_size: Number of lines available in the viewport.
            viewport_height: Number of lines available in the viewport.

        Returns:
            The rendered text for the currently visible transcript entries.
        """
        if self.buffer is None or self.renderer is None:
            return ""
        return self.visible_text(viewport_size, viewport_height)

    def visible_text(self, viewport_size: int | None = None, viewport_height: int | None = None) -> str:
        """Return the visible transcript text.

        Args:
            viewport_size: Number of lines available in the viewport.
            viewport_height: Number of lines available in the viewport.

        Returns:
            The rendered text for the currently visible transcript entries.
        """
        if self.buffer is None or self.renderer is None:
            return ""
        return self._visible_text_from_entries(self._resolve_active_entries(), viewport_size, viewport_height)

    def visible_entries(self, transcript_entries: Sequence[T]) -> list[T]:
        """Return the currently visible entries as a list.

        Args:
            transcript_entries: Transcript entries available for display.

        Returns:
            The currently visible transcript entries.
        """
        entry_count = len(transcript_entries)
        start_index = min(max(self.visible_start_index, 0), entry_count)
        end_index = min(max(self.visible_end_index, start_index), entry_count)
        return list(transcript_entries[start_index:end_index])
