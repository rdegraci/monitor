"""Transcript buffer state for the Monitor OOP TUI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(slots=True)
class TranscriptEntry:
    """A single transcript line for the output pane."""

    role: Literal["user", "assistant", "error", "subagent"]
    text: str


@dataclass(slots=True)
class TranscriptBuffer:
    """Own transcript state and append operations."""

    _entries: list[TranscriptEntry] = field(default_factory=list)

    def _append_entry(self, entry: TranscriptEntry) -> None:
        self._entries.append(entry)

    def _entries_copy(self) -> list[TranscriptEntry]:
        return list(self._entries)

    def append(self, role: str, text: str) -> None:
        """Append a transcript line."""
        self._append_entry(TranscriptEntry(role=role, text=text))

    def snapshot(self) -> list[TranscriptEntry]:
        """Return a renderable snapshot of transcript entries."""
        return self._entries_copy()

    def __len__(self) -> int:
        return len(self._entries)

    def __getitem__(
        self, item: slice | int
    ) -> list[TranscriptEntry] | TranscriptEntry:
        return self._entries[item]

    @property
    def entries(self) -> list[TranscriptEntry]:
        """Return the transcript history as a shallow copy."""
        return self._entries_copy()
