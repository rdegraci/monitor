"""Compaction summary persistence for Monitor OOP.

Compaction summaries written here are **forensic artifacts only**: nothing in
the running application reads them back. They exist so an operator can inspect
what was discarded during a compaction event, diagnose summarization quality
regressions, or replay history offline. The runtime never restores a session
from these files. As a result:

- Failure to persist a summary is logged but does not affect the user's turn.
- Files older than ``_RETENTION_SECONDS`` are deleted opportunistically on
  each successful save so the directory does not grow unbounded.
- The runtime is free to read the latest in-memory summary; on-disk files are
  only consulted by a human (or external tooling).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from time import strftime


logger = logging.getLogger(__name__)


_RETENTION_SECONDS = 30 * 24 * 60 * 60  # 30 days


@dataclass(slots=True)
class CompactionStore:
    """Persist compacted summaries to disk as forensic-only artifacts.

    This dataclass is the persistence boundary for compacted summaries.
    Instances encapsulate the filesystem location used to write summary
    artifacts. Files are intended for human inspection / offline tooling only —
    the running application never reads them back. See the module docstring
    for the rationale.
    """

    base_dir: Path

    def _current_timestamp(self) -> str:
        """Return the current timestamp string in YYYY-MM-DD-HH-MM-SS format."""

        return strftime("%Y-%m-%d-%H-%M-%S")

    def _build_summary_path(self, pid: int | None = None, timestamp: str | None = None) -> Path:
        """Build a summary file path under the configured directory.

        Args:
            pid: Optional process identifier override.
            timestamp: Optional timestamp override in YYYY-MM-DD-HH-MM-SS format.

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
            timestamp: Optional timestamp override in YYYY-MM-DD-HH-MM-SS format.

        Returns:
            The path to the written summary file.
        """

        return self.save(summary_text, pid=pid, timestamp=timestamp)

    def save(self, summary_text: str, pid: int | None = None, timestamp: str | None = None) -> Path:
        """Save a compacted summary to disk.

        Collisions on the base filename are resolved by appending ``-N`` before
        the suffix, starting at 1 and incrementing until a free name is found.
        The create-then-write uses exclusive mode so concurrent writers cannot
        race onto the same path.

        After a successful write, summaries older than the configured retention
        window are swept opportunistically (best-effort; failures are logged
        but do not affect the return value).

        Args:
            summary_text: The summary text to persist.
            pid: Optional process identifier override.
            timestamp: Optional timestamp override in YYYY-MM-DD-HH-MM-SS format.

        Returns:
            The path to the written summary file.
        """

        self.base_dir.mkdir(parents=True, exist_ok=True)
        base_path = self._build_summary_path(pid=pid, timestamp=timestamp)
        base_path.parent.mkdir(parents=True, exist_ok=True)

        candidate = base_path
        counter = 1
        while True:
            try:
                with open(candidate, "x", encoding="utf-8") as summary_file:
                    summary_file.write(summary_text)
                break
            except FileExistsError:
                candidate = base_path.with_name(
                    f"{base_path.stem}-{counter}{base_path.suffix}"
                )
                counter += 1

        self._sweep_old_summaries()
        return candidate

    def _sweep_old_summaries(self, retention_seconds: int = _RETENTION_SECONDS) -> None:
        """Delete summary files older than the retention window.

        Best-effort: any per-file failure is logged and ignored so a partially
        failing sweep cannot block a successful save. Only files matching the
        ``compact-*.summary`` pattern are eligible — unrelated files in the
        directory are untouched.
        """

        if not self.base_dir.exists():
            return
        cutoff = time.time() - retention_seconds
        try:
            entries = list(self.base_dir.iterdir())
        except OSError:
            logger.exception(
                "Failed to enumerate compaction directory for retention sweep: %s",
                self.base_dir,
            )
            return
        for entry in entries:
            if not entry.is_file():
                continue
            name = entry.name
            if not (name.startswith("compact-") and name.endswith(".summary")):
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                continue
            try:
                entry.unlink()
            except OSError:
                logger.exception(
                    "Failed to remove old compaction summary: %s", entry
                )
