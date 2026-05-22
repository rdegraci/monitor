"""Find files by filename pattern, recursively, with sensible default excludes.

Tool entry point: ``find_files``. Registered in tool_definitions.py.

Always recurses from ``root``. Common build/cache directories (.git, node_modules,
.venv, __pycache__, DerivedData, .build, Pods, etc.) are pruned in-place during
walk so we don't descend into them — important for performance on iOS projects
with CocoaPods and Python projects with node_modules from frontend tooling.

Pattern semantics:
- Glob pattern matched against the BASENAME of each file
  (``*.py``, ``test_*.swift``, ``Manager*.swift``). Case-sensitive.
- A leading ``**/`` is stripped (recursion is always on, so the prefix is
  redundant).
- Patterns containing ``/`` after that stripping are rejected — fnmatch
  has surprising semantics across path separators (``*`` matches ``/``),
  which would silently mis-scope queries. To restrict to a subdirectory,
  use the ``root`` argument instead.
"""

import fnmatch
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Hard cap on results to keep tool output token-bounded.
MAX_RESULTS = 200

# Directories pruned by default. Build artifacts, VCS metadata, and language
# package directories that produce noise and slow walks when searching by name.
DEFAULT_EXCLUDED_DIRS = frozenset({
    # VCS
    ".git",
    ".hg",
    ".svn",
    # Python
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    # Node
    "node_modules",
    # IDE
    ".idea",
    ".vscode",
    # Build outputs
    "dist",
    "build",
    # iOS / Swift
    "DerivedData",
    ".build",
    "Pods",
    "Carthage",
})


def find_files(pattern: str, root: str | None = None, include_hidden: bool = False, max_results: int | None = None):
    """Find files matching a glob pattern under root, returning a structured result.

    Args:
        pattern: Glob pattern matched against each file's basename
            (``*.py``, ``test_*.swift``). A leading ``**/`` is stripped.
            Patterns containing ``/`` (after stripping) are rejected — use
            the ``root`` argument to scope to a subdirectory instead.
        root: Directory to search under. Defaults to current working directory.
        include_hidden: If True, also include hidden files and traverse into
            hidden directories. Default False.
        max_results: Cap on number of results returned. Default MAX_RESULTS (200).

    Returns:
        dict with keys:
          - results (list[str]): matching file paths, relative to root.
          - count (int): number of paths returned.
          - truncated (bool): True if more matches existed but were capped.
          - root (str): absolute path of root that was searched.
          - error (str | None): error message on failure.
    """
    if not isinstance(pattern, str) or not pattern.strip():
        return {
            "results": [],
            "count": 0,
            "truncated": False,
            "root": "",
            "error": "pattern must be a non-empty string",
        }

    if root is None:
        root_path = Path.cwd()
    else:
        try:
            root_path = Path(root).resolve()
        except (OSError, RuntimeError) as e:
            return {
                "results": [],
                "count": 0,
                "truncated": False,
                "root": str(root),
                "error": f"unable to resolve root: {e}",
            }

    if not root_path.is_dir():
        return {
            "results": [],
            "count": 0,
            "truncated": False,
            "root": str(root_path),
            "error": f"root is not a directory: {root_path}",
        }

    if not isinstance(max_results, int) or max_results <= 0:
        max_results = MAX_RESULTS

    # Normalize pattern. Strip a leading "**/" since recursion is implicit.
    match_pattern = pattern
    if match_pattern.startswith("**/"):
        match_pattern = match_pattern[3:]
    if not match_pattern:
        # Pattern was just "**/"; treat as match-all.
        match_pattern = "*"

    # Reject path-style patterns: fnmatch's `*` crosses `/`, which would
    # silently mis-scope queries like 'tests/test_*.py'. Force the caller to
    # use the `root` argument for directory scoping.
    if "/" in match_pattern:
        return {
            "results": [],
            "count": 0,
            "truncated": False,
            "root": str(root_path),
            "error": (
                f"pattern contains '/' which is not supported; use the "
                f"`root` argument to scope to a subdirectory and pass a "
                f"basename pattern (got: {pattern!r})"
            ),
        }

    logger.info(
        "find_files: pattern=%r match_pattern=%r root=%s max_results=%d",
        pattern, match_pattern, root_path, max_results,
    )

    results: list[str] = []
    truncated = False
    try:
        for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
            # Prune excluded directories in-place so os.walk doesn't recurse into them.
            if include_hidden:
                dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDED_DIRS]
            else:
                dirnames[:] = [
                    d for d in dirnames
                    if d not in DEFAULT_EXCLUDED_DIRS and not d.startswith(".")
                ]

            for filename in filenames:
                if not include_hidden and filename.startswith("."):
                    continue
                if not fnmatch.fnmatch(filename, match_pattern):
                    continue
                full_path = Path(dirpath) / filename
                try:
                    rel = str(full_path.relative_to(root_path))
                except ValueError:
                    rel = str(full_path)
                results.append(rel)
                if len(results) >= max_results:
                    truncated = True
                    break
            if truncated:
                break
    except OSError as e:
        return {
            "results": results,
            "count": len(results),
            "truncated": truncated,
            "root": str(root_path),
            "error": f"search error: {e}",
        }

    return {
        "results": results,
        "count": len(results),
        "truncated": truncated,
        "root": str(root_path),
        "error": None,
    }
