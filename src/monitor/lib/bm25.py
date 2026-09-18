"""Lightweight Okapi BM25 index for ranking source files by keyword relevance.

Built on demand from the working tree (via ``rg --files`` so ``.gitignore`` and
the same exclude globs as ripgrep search apply). No external IR dependency.
"""

from __future__ import annotations

import logging
import math
import os
import re
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Identifier-ish tokens: letters/digits/underscore, including leading underscore.
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")

# Split CamelCase / PascalCase into pieces while keeping the original token.
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[0-9]+")

MAX_FILE_BYTES = 256 * 1024
MAX_INDEXED_FILES = 5000
INDEX_TTL_SECONDS = 60.0
BM25_K1 = 1.2
BM25_B = 0.75
LIST_FILES_TIMEOUT_SECONDS = 30


def tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase terms suitable for BM25.

    Keeps whole identifiers and also emits CamelCase/snake fragments so a
    query like ``timeout redis`` can match ``redis_timeout`` / ``RedisTimeout``.
    """
    if not text:
        return []
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        lower = raw.lower()
        out.append(lower)
        if "_" in raw:
            out.extend(p for p in lower.split("_") if p and p != lower)
        elif any(c.isupper() for c in raw[1:]):
            parts = [p.lower() for p in _CAMEL_RE.findall(raw) if p]
            out.extend(p for p in parts if p != lower)
    return out


@dataclass
class Bm25Index:
    """In-memory BM25 index over file paths."""

    doc_ids: list[str] = field(default_factory=list)
    doc_len: list[int] = field(default_factory=list)
    # term -> {doc_index: tf}
    postings: dict[str, dict[int, int]] = field(default_factory=dict)
    avgdl: float = 0.0
    n_docs: int = 0
    built_at: float = 0.0
    root: str = ""

    def add_document(self, doc_id: str, text: str) -> None:
        tokens = tokenize(text)
        if not tokens:
            return
        idx = len(self.doc_ids)
        self.doc_ids.append(doc_id)
        self.doc_len.append(len(tokens))
        tf = Counter(tokens)
        for term, count in tf.items():
            bucket = self.postings.setdefault(term, {})
            bucket[idx] = count

    def finalize(self) -> None:
        self.n_docs = len(self.doc_ids)
        if self.n_docs:
            self.avgdl = sum(self.doc_len) / float(self.n_docs)
        else:
            self.avgdl = 0.0
        self.built_at = time.monotonic()

    def _idf(self, term: str) -> float:
        df = len(self.postings.get(term, ()))
        # Lucene-style IDF with floor so common terms don't go strongly negative.
        return math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))

    def score(self, query: str) -> list[tuple[str, float]]:
        """Return ``(doc_id, score)`` pairs sorted by descending score."""
        q_terms = tokenize(query)
        if not q_terms or self.n_docs == 0 or self.avgdl <= 0:
            return []

        scores: dict[int, float] = {}
        for term in set(q_terms):
            posting = self.postings.get(term)
            if not posting:
                continue
            idf = self._idf(term)
            for doc_idx, tf in posting.items():
                dl = self.doc_len[doc_idx]
                denom = tf + BM25_K1 * (1.0 - BM25_B + BM25_B * dl / self.avgdl)
                scores[doc_idx] = scores.get(doc_idx, 0.0) + idf * (
                    tf * (BM25_K1 + 1.0) / denom
                )

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        return [(self.doc_ids[i], s) for i, s in ranked if s > 0.0]

    def top_docs(self, query: str, k: int = 40) -> list[str]:
        return [doc_id for doc_id, _ in self.score(query)[:k]]


_INDEX_CACHE: dict[str, Bm25Index] = {}


def clear_bm25_cache() -> None:
    """Drop cached indexes (tests / :cd)."""
    _INDEX_CACHE.clear()


def _build_rg_files_command(
    directory: str,
    exclude_patterns: list[str],
) -> list[str]:
    cmd = ["rg", "--files"]
    for pat in exclude_patterns:
        cmd.extend(["-g", pat])
    cmd.append(directory)
    return cmd


def _list_source_files(
    directory: str,
    exclude_patterns: list[str],
) -> list[str]:
    """List files via ripgrep so .gitignore and exclude globs match search."""
    cmd = _build_rg_files_command(directory, exclude_patterns)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=LIST_FILES_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.info("BM25 file listing via rg failed: %s", exc)
        return []
    except Exception as exc:
        logger.info("BM25 file listing via rg failed: %s", exc)
        return []

    if result.returncode not in (0, 1):
        logger.info("BM25 rg --files exited %s: %s", result.returncode, (result.stderr or "")[:200])
        return []

    paths: list[str] = []
    for line in (result.stdout or "").splitlines():
        path = line.strip()
        if not path:
            continue
        # Reject lines that look like ripgrep match output (path:line:...), which
        # appear when tests mock subprocess.run with search stdout.
        if re.search(r":\d+:", path):
            continue
        if not os.path.isfile(path):
            continue
        paths.append(path)
        if len(paths) >= MAX_INDEXED_FILES:
            break
    return paths


def build_bm25_index(
    directory: str = ".",
    exclude_patterns: list[str] | None = None,
) -> Bm25Index:
    """Build a BM25 index for ``directory`` (honoring exclude globs)."""
    root = os.path.abspath(directory)
    index = Bm25Index(root=root)
    files = _list_source_files(directory, exclude_patterns or [])
    for path in files:
        try:
            size = os.path.getsize(path)
            if size <= 0 or size > MAX_FILE_BYTES:
                continue
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        # Prefer path relative to cwd when under root, for stable display.
        try:
            rel = os.path.relpath(path, root)
            doc_id = rel if not rel.startswith("..") else path
        except ValueError:
            doc_id = path
        index.add_document(doc_id, text)
    index.finalize()
    logger.info(
        "Built BM25 index under %s: %d docs, %d terms",
        root,
        index.n_docs,
        len(index.postings),
    )
    return index


def get_bm25_index(
    directory: str = ".",
    exclude_patterns: list[str] | None = None,
    *,
    force_rebuild: bool = False,
) -> Bm25Index | None:
    """Return a cached BM25 index, rebuilding when stale or forced."""
    root = os.path.abspath(directory)
    cached = _INDEX_CACHE.get(root)
    now = time.monotonic()
    if (
        not force_rebuild
        and cached is not None
        and cached.n_docs > 0
        and (now - cached.built_at) < INDEX_TTL_SECONDS
    ):
        return cached

    index = build_bm25_index(directory, exclude_patterns=exclude_patterns)
    if index.n_docs == 0:
        return None
    _INDEX_CACHE[root] = index
    return index
