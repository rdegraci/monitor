"""Wiki-related helper utilities for built-in commands."""

WIKI_FIX_MAX_REPLACEMENT_LINES = 3
WIKI_FIX_MAX_REPLACEMENT_CHARACTERS = 400
WIKI_FIX_MAX_DIFF_LINES = 20


def wiki_fix_diff_line_count(diff_text: str) -> int:
    """Count changed diff lines in a unified diff.

    Args:
        diff_text: Unified diff text.

    Returns:
        The number of changed lines excluding file headers and hunk markers.
    """
    return sum(
        1
        for line in diff_text.splitlines()
        if (line.startswith("+") and not line.startswith("+++"))
        or (line.startswith("-") and not line.startswith("---"))
    )
