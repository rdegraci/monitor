"""Deterministic bulk find-and-replace across one or more files.

The middle cell of Monitor's edit space:

    single-site exact   →  text_file_str_replace_in_file (exactly-one-match)
    multi-site mechanical →  bulk_replace_in_files  (THIS — deterministic)
    fuzzy / sweeping    →  modify_source_code      (LLM, non-deterministic)

This is the sanctioned path for *mechanical* multi-site edits (rename a symbol
at every call site, delete a marker everywhere, bulk substitution). It is fully
deterministic — same input → same output, no LLM in the loop — which makes it
both cheaper and safer than routing a mechanical change through the whole-file
LLM regeneration in ``modify_source_code``. Reserve ``modify_source_code`` for
genuinely fuzzy intent.

Safety posture (why this is not ``sed``):
- **Literal by default**; regex is strictly opt-in (``literal=False``) and
  pinned to Python ``re`` — no shell/BSD-vs-GNU ambiguity, no accidental
  metacharacters.
- **Word-boundary option** so renaming ``count`` never touches ``account``.
- **Dry-run by default** — previews the unified diff; writing requires an
  explicit ``dry_run=False``.
- **expected_count latch** — assert the match count or abort untouched.
- **Verification gate** — every changed file is validated (code / structured
  text) before any write; a batch is all-or-nothing.
- Replacement text is always literal (no regex backreference expansion), even
  in regex mode.
"""

from __future__ import annotations

import glob
import logging
import os
import re
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from monitor.lib.file_io import read_file, is_file
from monitor.lib.text_file_editor import _compute_and_print_diff, _truncate_diff
from monitor.lib.edit_verification import verify_file_content
from monitor.lib.colors import print_red, print_yellow

# NOTE: monitor.lib.safety is imported lazily inside bulk_replace_in_files.
# It pulls in monitor.config, which imports core.tools → tool_definitions,
# which imports THIS module — a module-level import would be circular. The
# surgical editors dodge the same cycle the same way (text_file_editor.py).

logger = logging.getLogger(__name__)

_GLOB_CHARS = ("*", "?", "[")
_BINARY_SNIFF_BYTES = 8192

TOOL_LABEL = "bulk_replace_in_files"


def _repo_root() -> Optional[str]:
    """Walk up from cwd to the nearest directory containing .git; None if none."""
    d = os.path.realpath(os.getcwd())
    while True:
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _is_binary(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(_BINARY_SNIFF_BYTES)
    except OSError:
        return True


def _atomic_write(path: str, content: str) -> None:
    """Write content to path atomically (temp file in same dir + os.replace)."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".bulk_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _make_matcher(
    old: str, new: str, literal: bool, word_boundary: bool
) -> Tuple[Optional[Callable[[str], Tuple[str, int]]], Optional[str]]:
    """Build a (content) -> (new_content, count) function, or (None, error)."""
    # Fast path: plain literal substring replace-all.
    if literal and not word_boundary:
        def _literal(content: str) -> Tuple[str, int]:
            count = content.count(old)
            return (content.replace(old, new) if count else content), count
        return _literal, None

    # Regex path (word-boundary and/or user-supplied regex).
    pattern = re.escape(old) if literal else old
    if word_boundary:
        pattern = r"\b" + pattern + r"\b"
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return None, f"Invalid regex pattern: {e}"

    # Replacement is treated literally (no backreference expansion) by using a
    # function repl — deterministic and free of \1 surprises.
    def _regex(content: str) -> Tuple[str, int]:
        return rx.subn(lambda _m: new, content)

    return _regex, None


def _resolve_paths(
    paths: Union[str, List[str]]
) -> Tuple[List[str], List[Dict[str, str]]]:
    """Resolve explicit paths and/or globs to a concrete file list + skip list."""
    if isinstance(paths, str):
        items: List[str] = [paths]
    elif isinstance(paths, (list, tuple)):
        items = [str(p) for p in paths]
    else:
        return [], [{"path": str(paths), "reason": "invalid paths type"}]

    root = _repo_root()
    seen: set = set()
    files: List[str] = []
    skipped: List[Dict[str, str]] = []

    for item in items:
        if any(ch in item for ch in _GLOB_CHARS):
            matches = sorted(glob.glob(os.path.expanduser(item), recursive=True))
            if not matches:
                skipped.append({"path": item, "reason": "no match"})
        else:
            matches = [item]

        for m in matches:
            rp = os.path.realpath(os.path.expanduser(m))
            if rp in seen:
                continue
            seen.add(rp)
            if not is_file(m):
                skipped.append({"path": m, "reason": "not a file"})
                continue
            if root and rp != root and not rp.startswith(root + os.sep):
                skipped.append({"path": m, "reason": "outside repo working tree"})
                continue
            if _is_binary(m):
                skipped.append({"path": m, "reason": "binary"})
                continue
            files.append(m)

    return files, skipped


def bulk_replace_in_files(
    old: str,
    new: str,
    paths: Union[str, List[str]],
    literal: bool = True,
    word_boundary: bool = False,
    expected_count: Optional[int] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Deterministically replace ``old`` with ``new`` across the given paths.

    Args:
        old: text/pattern to find (non-empty).
        new: replacement text (literal — no regex backreference expansion).
        paths: a file path, a glob (e.g. ``src/**/*.py``), or a list of either.
        literal: literal substring match (default True); set False for regex.
        word_boundary: match whole identifiers only (rename-safe).
        expected_count: if set, abort unless exactly this many matches are found.
        dry_run: preview only (default True); set False to write.

    Returns a structured dict; never raises for a user/content error.
    """
    # --- input validation ---
    if not isinstance(old, str) or old == "":
        return {"ok": False, "error": "old must be a non-empty string"}
    if not isinstance(new, str):
        return {"ok": False, "error": "new must be a string"}

    from monitor.lib.safety import check_write_size  # lazy: avoids import cycle

    ok, err = check_write_size(new, TOOL_LABEL)
    if not ok:
        print_red(err)
        return {"ok": False, "error": err}

    matcher, m_err = _make_matcher(old, new, literal, word_boundary)
    if matcher is None:
        print_red(m_err)
        return {"ok": False, "error": m_err}

    files, skipped = _resolve_paths(paths)
    if not files:
        msg = f"No editable files matched: {paths!r}"
        return {"ok": False, "error": msg, "skipped": skipped}

    # --- compute replacements in memory (no writes yet) ---
    pending: List[Tuple[str, str, str, int]] = []  # (path, original, new_content, count)
    total = 0
    for path in files:
        original = read_file(path)
        if original is None:
            skipped.append({"path": path, "reason": "unreadable"})
            continue
        new_content, count = matcher(original)
        if count == 0:
            continue
        total += count
        pending.append((path, original, new_content, count))

    # --- expected_count latch (before any write) ---
    if expected_count is not None and total != expected_count:
        msg = (
            f"expected_count={expected_count} but found {total} occurrence(s); "
            f"no changes written"
        )
        print_red(msg)
        return {
            "ok": False,
            "error": msg,
            "occurrences": total,
            "files_changed": len(pending),
            "skipped": skipped,
        }

    if not pending:
        return {
            "ok": True,
            "dry_run": dry_run,
            "occurrences": 0,
            "files_changed": 0,
            "files_scanned": len(files),
            "per_file": [],
            "skipped": skipped,
            "message": f"No occurrences of the pattern found in {len(files)} file(s).",
        }

    # --- verification gate: validate ALL changed files before ANY write ---
    verification_failures: List[Dict[str, str]] = []
    for path, _original, new_content, _count in pending:
        v_ok, v_err, _tier = verify_file_content(path, new_content)
        if not v_ok:
            verification_failures.append({"path": path, "error": v_err})
    if verification_failures:
        msg = "verification failed; no changes written (batch is all-or-nothing)"
        print_red(msg)
        return {
            "ok": False,
            "error": msg,
            "verification_failures": verification_failures,
            "occurrences": total,
            "files_changed": len(pending),
            "skipped": skipped,
        }

    # --- build per-file diffs (prints highlighted diff to terminal) ---
    per_file: List[Dict[str, Any]] = []
    for path, original, new_content, count in pending:
        diff = _compute_and_print_diff(original, new_content, path)
        per_file.append({"path": path, "count": count, "diff": _truncate_diff(diff)})

    # --- dry run: preview, write nothing ---
    if dry_run:
        msg = (
            f"DRY RUN: would replace {total} occurrence(s) in {len(pending)} file(s). "
            f"Re-run with dry_run=false to apply."
        )
        print_yellow(msg)
        return {
            "ok": True,
            "dry_run": True,
            "occurrences": total,
            "files_changed": len(pending),
            "files_scanned": len(files),
            "per_file": per_file,
            "skipped": skipped,
            "message": msg,
        }

    # --- commit: write all changed files; best-effort rollback on failure ---
    written: List[Tuple[str, str]] = []  # (path, original) for rollback
    try:
        for path, original, new_content, _count in pending:
            _atomic_write(path, new_content)
            written.append((path, original))
    except Exception as e:  # pragma: no cover - filesystem failure path
        for p, orig in written:
            try:
                _atomic_write(p, orig)
            except Exception:
                logger.error("Rollback failed for %s; file may be modified", p)
        msg = f"write failed ({e}); rolled back {len(written)} file(s), no net change"
        print_red(msg)
        return {"ok": False, "error": msg, "skipped": skipped}

    msg = f"Replaced {total} occurrence(s) in {len(pending)} file(s)."
    print_yellow(msg)
    logger.info(msg)
    return {
        "ok": True,
        "dry_run": False,
        "occurrences": total,
        "files_changed": len(pending),
        "files_scanned": len(files),
        "per_file": per_file,
        "skipped": skipped,
        "message": msg,
    }
