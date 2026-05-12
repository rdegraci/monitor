"""Compaction summary persistence for Monitor OOP."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import strftime
import os


@dataclass(slots=True)
class CompactionStore:
    """Persist compacted summaries to disk.

    This dataclass is the persistence boundary for compacted summaries.
    Instances encapsulate the filesystem location used to write summary
    artifacts without altering the summary contents or persistence flow.
    """

    base_dir: Path

    def _current_timestamp(self) -> str:
        """Return the current timestamp string in YYYY-MM-DD-HH-MM format."""

        return strftime("%Y-%m-%d-%H-%M")

    def _build_summary_path(self, pid: int | None = None, timestamp: str | None = None) -> Path:
        """Build a summary file path under the configured directory.

        Args:
            pid: Optional process identifier override.
            timestamp: Optional timestamp override in YYYY-MM-DD-HH-MM format.

        Returns:
            The target summary file path.
        """

        current_pid = os.getpid() if pid is None else pid
        current_timestamp = self._current_timestamp() if timestamp is None else timestamp
        return self.base_dir / f"compact-{current_pid}-{current_timestamp}.summary"

    def persist_summary(self, summary_text: str, pid: int | None = None, timestamp: str | None = None) -> Path:
        """Persist a compacted summary to disk.

        Args:
            summary_text: The summary text to persist.
            pid: Optional process identifier override.
            timestamp: Optional timestamp override in YYYY-MM-DD-HH-MM format.

        Returns:
            The path to the written summary file.
        """

        return self.save(summary_text, pid=pid, timestamp=timestamp)

    def save(self, summary_text: str, pid: int | None = None, timestamp: str | None = None) -> Path:
        """Save a compacted summary to disk.

        Args:
            summary_text: The summary text to persist.
            pid: Optional process identifier override.
            timestamp: Optional timestamp override in YYYY-MM-DD-HH-MM format.

        Returns:
            The path to the written summary file.
        """

        self.base_dir.mkdir(parents=True, exist_ok=True)
        summary_path = self._build_summary_path(pid=pid, timestamp=timestamp)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(summary_text, encoding="utf-8")
        return summary_path
