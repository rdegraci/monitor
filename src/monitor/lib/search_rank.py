"""Query routing helpers and ripgrep-output reranking for code search.

Used by ``ripgrep_search`` so the LLM search tool can:
  - treat single-token / regex queries as exact full-tree searches
  - treat multi-word queries as topical (BM25 shortlist first)
  - reorder match blocks by relevance before context truncation
"""

from __future__ import annotations

import re
from monitor.lib.bm25 import tokenize

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# ripgrep --pretty / --heading content lines: "12: text" or "12- text"
_RG_CONTENT_LINE_RE = re.compile(r"^\s*\d+[:\-].*")
# Classic non-pretty: path:line:text (also path:line-text for context in some modes)
_RG_PATH_LINE_RE = re.compile(r"^(.+?):(\d+)[:\-].*")


def strip_ansi(text: str) -> str:
    if not text:
        return text
    return _ANSI_RE.sub("", text)


def is_topical_query(term: str, *, regex: bool = False) -> bool:
    """True when the query looks multi-term / topical rather than an exact literal.

    Regex searches stay on the full-tree exact path — BM25 cannot usefully
    shortlist for arbitrary regex patterns.
    """
    if regex:
        return False
    if not term or not str(term).strip():
        return False
    # Two or more whitespace-separated tokens → topical.
    return len(str(term).split()) >= 2


def split_rg_output_blocks(stdout: str) -> list[str]:
    """Split ripgrep stdout into per-file blocks (best-effort).

    Supports:
      - ``--pretty`` / heading mode: path on its own line, then numbered lines
      - classic ``path:line:text`` mode: contiguous lines sharing a path
    """
    if not stdout:
        return []

    lines = stdout.splitlines(keepends=True)
    if not lines:
        return []

    # Detect classic path:line: mode from the first non-empty plain line.
    first_plain = ""
    for line in lines:
        plain = strip_ansi(line).rstrip("\n")
        if plain.strip():
            first_plain = plain
            break

    if first_plain and _RG_PATH_LINE_RE.match(first_plain) and not _looks_like_heading_mode(lines):
        return _split_classic_blocks(lines)

    return _split_heading_blocks(lines)


def _looks_like_heading_mode(lines: list[str]) -> bool:
    """Heading mode has a bare path line followed by a numbered content line."""
    saw_path = False
    for line in lines:
        plain = strip_ansi(line).rstrip("\n")
        if not plain.strip():
            if saw_path:
                continue
            continue
        if _RG_CONTENT_LINE_RE.match(plain):
            return saw_path
        if _RG_PATH_LINE_RE.match(plain):
            return False
        # Bare path (no :digits:).
        saw_path = True
    return False


def _split_heading_blocks(lines: list[str]) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if current:
            blocks.append("".join(current))
            current = []

    for line in lines:
        plain = strip_ansi(line).rstrip("\n")
        is_blank = not plain.strip()
        is_content = bool(_RG_CONTENT_LINE_RE.match(plain))
        is_classic = bool(_RG_PATH_LINE_RE.match(plain))
        is_path_header = (
            not is_blank and not is_content and not is_classic and plain.strip() == plain
        )

        if is_path_header and current:
            # New file section.
            flush()
            current.append(line)
            continue
        if is_blank and current and _block_has_content(current):
            # Blank line after a complete block — keep inside block or treat as separator.
            # Ripgrep separates files with a blank line; flush on blank after content.
            current.append(line)
            flush()
            continue
        current.append(line)

    flush()
    return [b for b in blocks if strip_ansi(b).strip()]


def _block_has_content(block_lines: list[str]) -> bool:
    for line in block_lines:
        plain = strip_ansi(line).rstrip("\n")
        if _RG_CONTENT_LINE_RE.match(plain) or _RG_PATH_LINE_RE.match(plain):
            return True
    return False


def _split_classic_blocks(lines: list[str]) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    current_path: str | None = None

    def flush() -> None:
        nonlocal current, current_path
        if current:
            blocks.append("".join(current))
        current = []
        current_path = None

    for line in lines:
        plain = strip_ansi(line).rstrip("\n")
        match = _RG_PATH_LINE_RE.match(plain)
        if match:
            path = match.group(1)
            if current_path is not None and path != current_path:
                flush()
            current_path = path
            current.append(line)
        else:
            if current:
                current.append(line)
            elif plain.strip():
                # Orphan line — start a block.
                current.append(line)

    flush()
    return [b for b in blocks if strip_ansi(b).strip()]


def score_block(block: str, query: str) -> float:
    """Score a match block by query-term presence (path + body)."""
    terms = list(dict.fromkeys(tokenize(query)))
    if not terms:
        return 0.0
    plain = strip_ansi(block).lower()
    score = 0.0
    # Path is usually the first line in heading mode.
    first_line = plain.split("\n", 1)[0]
    for term in terms:
        if not term:
            continue
        body_count = plain.count(term)
        path_count = first_line.count(term)
        score += body_count
        score += 3.0 * path_count  # path hits are strong signals
    return score


def rerank_rg_output(stdout: str, query: str) -> str:
    """Reorder per-file ripgrep blocks by descending relevance to ``query``.

    Returns ``stdout`` unchanged when there is nothing useful to reorder.
    """
    if not stdout or not query:
        return stdout

    blocks = split_rg_output_blocks(stdout)
    if len(blocks) <= 1:
        return stdout

    ranked = sorted(
        blocks,
        key=lambda b: score_block(b, query),
        reverse=True,
    )
    # Preserve a trailing newline if the original had one.
    joined = "".join(ranked)
    if stdout.endswith("\n") and not joined.endswith("\n"):
        joined += "\n"
    return joined
