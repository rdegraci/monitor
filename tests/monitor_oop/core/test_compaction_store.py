"""Tests for the isolated Monitor OOP compaction store."""
from __future__ import annotations

import os
import time
from pathlib import Path

from monitor_oop.core.compaction_store import CompactionStore


def test_compaction_store_writes_timestamped_summary_file(tmp_path: Path) -> None:
    """Verify compaction summaries are written using the required filename format."""

    store = CompactionStore(tmp_path)

    summary_path = store.save(
        "summary text",
        pid=1234,
        timestamp="2026-03-10-23-01-45",
    )

    assert summary_path.name == "compact-1234-2026-03-10-23-01-45.summary"
    assert summary_path.read_text(encoding="utf-8") == "summary text"


def test_compaction_store_appends_counter_on_collision(tmp_path: Path) -> None:
    """Verify same-second collisions append an incrementing -N suffix."""

    store = CompactionStore(tmp_path)
    common = {"pid": 1234, "timestamp": "2026-03-10-23-01-45"}

    first = store.save("first", **common)
    second = store.save("second", **common)
    third = store.save("third", **common)

    assert first.name == "compact-1234-2026-03-10-23-01-45.summary"
    assert second.name == "compact-1234-2026-03-10-23-01-45-1.summary"
    assert third.name == "compact-1234-2026-03-10-23-01-45-2.summary"
    assert first.read_text(encoding="utf-8") == "first"
    assert second.read_text(encoding="utf-8") == "second"
    assert third.read_text(encoding="utf-8") == "third"


def test_compaction_store_sweeps_summaries_older_than_retention(tmp_path: Path) -> None:
    """Verify save() removes compact-*.summary files older than 30 days and keeps newer ones."""

    store = CompactionStore(tmp_path)

    # Stale: 40 days old.
    stale = store.save("stale", pid=1, timestamp="2020-01-01-00-00-00")
    stale_mtime = time.time() - (40 * 24 * 60 * 60)
    os.utime(stale, (stale_mtime, stale_mtime))

    # Fresh: 10 days old, should survive.
    fresh = store.save("fresh", pid=2, timestamp="2020-01-02-00-00-00")
    fresh_mtime = time.time() - (10 * 24 * 60 * 60)
    os.utime(fresh, (fresh_mtime, fresh_mtime))

    # Unrelated file, must not be deleted.
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("keep me")
    unrelated_mtime = time.time() - (90 * 24 * 60 * 60)
    os.utime(unrelated, (unrelated_mtime, unrelated_mtime))

    # Triggers the sweep at end of save().
    new_path = store.save("current", pid=3, timestamp="2020-01-03-00-00-00")

    assert not stale.exists()
    assert fresh.exists()
    assert new_path.exists()
    assert unrelated.exists()
