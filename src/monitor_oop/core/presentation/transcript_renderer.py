"""Transcript rendering for the Monitor OOP TUI."""
from __future__ import annotations

from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.formatted_text import to_formatted_text
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import BashLexer

from monitor_oop.core.presentation.transcript_buffer import TranscriptEntry


class TranscriptRenderer:
    """Render transcript entries for the output pane."""

    def format(self, entries: list[TranscriptEntry]) -> str:
        """Format transcript entries as plain text.

        Args:
            entries: The transcript entries to format.

        Returns:
            A plain-text string compatible with TranscriptViewport.get_formatted_text.
        """
        return self.render_text(entries)

    def line_count(self, entries: list[TranscriptEntry]) -> int:
        """Count the number of display lines produced for transcript entries.

        Args:
            entries: The transcript entries to measure.

        Returns:
            The number of display lines produced by render_text.
        """
        return self.render_text(entries).count("\n") + 1 if entries else 0

    def render(self, entries: list[TranscriptEntry]) -> list[tuple[str, str]]:
        """Render the transcript entries to display fragments."""
        fragments: list[tuple[str, str]] = []
        for index, entry in enumerate(entries):
            if index > 0:
                fragments.append(("", "\n"))
            fragments.extend(self._render_entry(entry))
        return fragments

    def render_text(self, entries: list[TranscriptEntry]) -> str:
        """Render the transcript entries to plain text for compatibility."""
        fragments = self.render(entries)
        return "".join(fragment for _, fragment in fragments)

    def _render_entry(self, entry: TranscriptEntry) -> list[tuple[str, str]]:
        """Render a single transcript entry as formatted fragments."""
        if entry.role == "user":
            return [("", f"> {entry.text}")]
        if entry.role == "assistant":
            return self._render_assistant_entry(entry)
        if entry.role == "error":
            return [("", f"ERROR: {entry.text}")]
        if entry.role == "subagent":
            return [("", f"SUBAGENT: {entry.text}")]
        return [("", entry.text)]

    def _render_assistant_entry(self, entry: TranscriptEntry) -> list[tuple[str, str]]:
        """Render an assistant entry at the formatting boundary."""
        highlighted_stx = [("fg:yellow", "STX")]
        highlighted_etx = [("fg:yellow", "ETX")]
        highlighted_text = self._highlight_assistant_text(entry.text)
        return [
            *highlighted_stx,
            ("\n", "\n"),
            *highlighted_text,
            ("\n", "\n"),
            *highlighted_etx,
        ]

    def _highlight_assistant_text(self, text: str) -> list[tuple[str, str]]:
        """Apply Bash syntax highlighting to assistant transcript text."""
        highlighted_text = highlight(text, BashLexer(), TerminalFormatter())
        return to_formatted_text(ANSI(highlighted_text))
