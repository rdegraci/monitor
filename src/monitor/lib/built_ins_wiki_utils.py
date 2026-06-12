"""Wiki-related helper utilities for built-in commands."""

from typing import Any

WIKI_FIX_MAX_REPLACEMENT_LINES = 3
WIKI_FIX_MAX_REPLACEMENT_CHARACTERS = 400
WIKI_FIX_MAX_DIFF_LINES = 20

_LATEST_WIKI_FIX_PREVIEWS: dict[str, dict[str, Any]] = {}


def store_latest_wiki_fix_preview(preview: dict[str, Any]) -> dict[str, Any]:
    """Store a generated wiki-fix preview for later application.

    Args:
        preview: Preview result dictionary containing at least ``finding_id``.

    Returns:
        The stored preview dictionary.
    """
    finding_id = str(preview.get("finding_id", ""))
    if finding_id:
        _LATEST_WIKI_FIX_PREVIEWS[finding_id] = preview
    return preview


def latest_wiki_fix_preview(finding_id: str) -> dict[str, Any] | None:
    """Return the latest stored wiki-fix preview for a finding id.

    Args:
        finding_id: Stable finding id associated with the preview.

    Returns:
        The stored preview dictionary, or ``None`` if no preview is stored.
    """
    return _LATEST_WIKI_FIX_PREVIEWS.get(finding_id)


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
