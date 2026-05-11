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

    def append(self, role: str, text: str) -> None:
        """Append a transcript line."""
        self._entries.append(TranscriptEntry(role=role, text=text))

    def snapshot(self) -> list[TranscriptEntry]:
        """Return a renderable snapshot of transcript entries."""
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __getitem__(
        self, item: slice | int
    ) -> list[TranscriptEntry] | TranscriptEntry:
        return self._entries[item]

    @property
    def entries(self) -> list[TranscriptEntry]:
        """Return the transcript history as a shallow copy."""
        return list(self._entries)
