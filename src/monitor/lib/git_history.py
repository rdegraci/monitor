"""Read-only git history tools for the LLM: pickaxe, blame, and commit-range diff.

All are scoped, output-capped, and timeout-bounded. Commands run as a list (no
shell). Paths follow a ``--`` separator so a path starting with ``-`` can't be
parsed as an option; the pickaxe query is glued to its flag (``-S<query>`` /
``-G<query>``) so a query starting with ``-`` is treated as the search string;
and refs are rejected if they start with ``-`` (git refnames never do), which
closes the same option-injection gap for the diff-range positions.
"""

import logging
import subprocess

logger = logging.getLogger(__name__)

HISTORY_TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 10000


def _run_git(cmd):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=HISTORY_TIMEOUT_SECONDS,
    )


def _truncate(text):
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "\n... [output truncated] ..."


def search_commit_history(query, regex=False, path=None, max_results=20):
    """Find commits that introduced or removed a piece of code/text (git pickaxe).

    Args:
        query: The code or text to look for across history.
        regex: Treat ``query`` as a regular expression (-G) instead of a literal
            string (-S).
        path: Optional file or directory to scope the search.
        max_results: Max number of commits to return (newest first).

    Returns:
        str: Matching commits as "<short-hash> <date> <subject>" lines, a
            "no commits found" message, or an "Error: ..." string.
    """
    if not query or not str(query).strip():
        return "Error: 'query' is required (the code or text to search for)."
    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        max_results = 20
    if max_results <= 0:
        max_results = 20

    flag = f"-G{query}" if regex else f"-S{query}"
    cmd = [
        "git", "--no-pager", "log",
        f"--max-count={max_results}",
        "--date=short",
        "--format=%h %ad %s",
        flag,
        "--",
    ]
    if path:
        cmd.append(path)

    try:
        result = _run_git(cmd)
    except subprocess.TimeoutExpired:
        return f"Error: git history search timed out after {HISTORY_TIMEOUT_SECONDS}s."
    except FileNotFoundError:
        return "Error: git executable not found."

    if result.returncode != 0:
        return f"Error running git log: {result.stderr.strip() or 'unknown error'}"

    out = result.stdout.strip()
    if not out:
        kind = "matching regex" if regex else "containing"
        return f"No commits found that added or removed text {kind}: {query}"
    return _truncate(out)


def blame_lines(path, start_line, end_line):
    """Show which commit last changed each line in a range of a file (git blame).

    Args:
        path: File to blame.
        start_line: First line (1-based).
        end_line: Last line (1-based, >= start_line).

    Returns:
        str: git blame output for the range, or an "Error: ..." string.
    """
    if not path or not str(path).strip():
        return "Error: 'path' is required."
    try:
        start_line = int(start_line)
        end_line = int(end_line)
    except (TypeError, ValueError):
        return "Error: start_line and end_line must be integers."
    if start_line < 1 or end_line < start_line:
        return "Error: require start_line >= 1 and end_line >= start_line."

    cmd = [
        "git", "--no-pager", "blame",
        "-L", f"{start_line},{end_line}",
        "--date=short",
        "--", path,
    ]

    try:
        result = _run_git(cmd)
    except subprocess.TimeoutExpired:
        return f"Error: git blame timed out after {HISTORY_TIMEOUT_SECONDS}s."
    except FileNotFoundError:
        return "Error: git executable not found."

    if result.returncode != 0:
        return f"Error running git blame: {result.stderr.strip() or 'unknown error'}"

    out = result.stdout.strip()
    if not out:
        return f"No blame output for {path}:{start_line},{end_line}"
    return _truncate(out)


def perform_git_diff_range(base, target, path=None):
    """Diff between two arbitrary commits/branches/tags (git diff <base> <target>).

    Args:
        base: The starting ref (commit hash, branch, or tag).
        target: The ending ref to compare against base.
        path: Optional file or directory to limit the diff to.

    Returns:
        str: The diff output, a "no differences" message, or an "Error: ..." string.
    """
    base = base.strip() if isinstance(base, str) else ""
    target = target.strip() if isinstance(target, str) else ""
    if not base or not target:
        return "Error: both 'base' and 'target' refs are required."
    # git refnames never start with '-'; rejecting it closes option-injection
    # for the ref positions (which sit before the '--' path separator).
    if base.startswith("-") or target.startswith("-"):
        return "Error: refs must not start with '-'."

    cmd = ["git", "--no-pager", "diff", base, target, "--"]
    if path:
        cmd.append(path)

    try:
        result = _run_git(cmd)
    except subprocess.TimeoutExpired:
        return f"Error: git diff timed out after {HISTORY_TIMEOUT_SECONDS}s."
    except FileNotFoundError:
        return "Error: git executable not found."

    if result.returncode != 0:
        return f"Error running git diff: {result.stderr.strip() or 'unknown error'}"

    out = result.stdout.strip()
    if not out:
        scope = f" for {path}" if path else ""
        return f"No differences between {base} and {target}{scope}."
    return _truncate(out)
