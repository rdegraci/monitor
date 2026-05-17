"""Tests for transcript buffer behavior in Monitor OOP."""
from __future__ import annotations

from monitor_oop.core.presentation.transcript_buffer import TranscriptBuffer


def test_transcript_buffer_appends_and_returns_copies() -> None:
    """Verify transcript entries are appended and exposed as shallow copies."""

    buffer = TranscriptBuffer()

    buffer.append("user", "hello")
    buffer.append("assistant", "world")

    snapshot = buffer.snapshot()

    assert len(buffer) == 2
    assert buffer.entries[0].text == "hello"
    assert buffer.entries[1].role == "assistant"
    assert snapshot[0].text == "hello"
    assert snapshot[1].text == "world"
    assert snapshot is not buffer.entries
