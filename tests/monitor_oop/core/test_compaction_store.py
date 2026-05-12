"""Tests for the isolated Monitor OOP compaction store."""
from __future__ import annotations

from pathlib import Path

from monitor_oop.core.compaction_store import CompactionStore


def test_compaction_store_writes_timestamped_summary_file(tmp_path: Path) -> None:
    """Verify compaction summaries are written using the required filename format."""

    store = CompactionStore(tmp_path)

    summary_path = store.save(
        "summary text",
        pid=1234,
        timestamp="2026-03-10-23-01",
    )

    assert summary_path.name == "compact-1234-2026-03-10-23-01.summary"
    assert summary_path.read_text(encoding="utf-8") == "summary text"
