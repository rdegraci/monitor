"""Deterministic-edit preference and actionable tool failures (PLAN Phase 7).

Goals:

- Prefer surgical create/replace/insert/bulk edits over natural-language
  ``modify_source_code``.
- Return short, category-tagged failure messages with one recovery step.
- Block pointless retries: exact-arg repeats and path-scoped read hunting
  (e.g. sliding ``cat_file`` ranges forever looking for a string).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from monitor import config

logger = logging.getLogger(__name__)

# --- Categories (stable strings for tests / metrics) ------------------------

CATEGORY_INVALID_ARGUMENTS = "invalid_arguments"
CATEGORY_MISSING_MATCH = "missing_match"
CATEGORY_TEST_FAILURE = "test_failure"
CATEGORY_OVERSIZED_OUTPUT = "oversized_output"
CATEGORY_CONTEXT_PRESSURE = "context_pressure"
CATEGORY_PROVIDER_ERROR = "provider_error"
CATEGORY_PERMISSION_DENIED = "permission_denied"
CATEGORY_LOOP_REJECTED = "loop_rejected"
CATEGORY_READ_BUDGET = "read_budget"
CATEGORY_UNKNOWN = "unknown"

DETERMINISTIC_EDIT_TOOLS = frozenset(
    {
        "text_file_create",
        "text_file_str_replace_in_file",
        "text_file_insert_text_at_line",
        "bulk_replace_in_files",
        "create_file",
    }
)

NL_EDIT_TOOLS = frozenset({"modify_source_code"})

READ_BUDGET_TOOLS = frozenset(
    {
        "cat_file",
        "cat_file_range",
        "text_file_or_directory_view",
    }
)

# Preferred edit order for docs / notices (create → replace → insert → bulk → NL).
PREFERRED_EDIT_ORDER = (
    "text_file_create",
    "text_file_str_replace_in_file",
    "text_file_insert_text_at_line",
    "bulk_replace_in_files",
    "modify_source_code",
)

_RECOVERY = {
    CATEGORY_INVALID_ARGUMENTS: "Fix the arguments (types, required fields, ranges) and retry once.",
    CATEGORY_MISSING_MATCH: "Re-read the file, then widen or uniquify the match; do not switch to modify_source_code yet.",
    CATEGORY_TEST_FAILURE: "Inspect the failing assertion/traceback, apply a surgical fix, then re-run the same tests.",
    CATEGORY_OVERSIZED_OUTPUT: "Narrow the request (smaller range, fewer files, or a search tool) and retry.",
    CATEGORY_CONTEXT_PRESSURE: "Use :compact or :break_chain, then continue with a smaller context.",
    CATEGORY_PROVIDER_ERROR: "Retry once; if it persists, switch model or wait and ask the user.",
    CATEGORY_PERMISSION_DENIED: "Check path ownership/permissions, or ask the user for access.",
    CATEGORY_LOOP_REJECTED: "Change arguments or strategy — repeating the same call will not help.",
    CATEGORY_READ_BUDGET: "Stop paging this file. Use ripgrep_search_tool (or find_files) to locate text, then open one targeted range.",
    CATEGORY_UNKNOWN: "Change approach or ask the user for guidance.",
}

# Per-turn ledgers (cleared by reset_tool_hygiene_state).
_RECENT_TOOL_CALLS: list[str] = []
_PATH_READ_COUNTS: Dict[str, int] = {}
_NL_FALLBACK_NOTICED_THIS_TURN = False


def reset_tool_hygiene_state() -> None:
    """Clear per-turn loop and read-budget ledgers (call at turn start)."""
    global _NL_FALLBACK_NOTICED_THIS_TURN
    _RECENT_TOOL_CALLS.clear()
    _PATH_READ_COUNTS.clear()
    _NL_FALLBACK_NOTICED_THIS_TURN = False


def _path_from_args(args: Any) -> Optional[str]:
    if not isinstance(args, dict):
        return None
    for key in ("path", "source_file", "file"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def tool_call_signature(name: str, args: Any) -> str:
    """Stable signature for exact-arg loop detection."""
    import json

    try:
        canonical = json.dumps(args, sort_keys=True, default=str) if args else "{}"
    except Exception:
        canonical = repr(args)
    return f"{name}:{canonical}"


def check_exact_repeat(name: str, args: Any) -> Optional[str]:
    """Record a call; return an actionable rejection if exact args repeat too often."""
    max_reps = int(getattr(config, "MAX_REPEATED_TOOL_CALLS", 3) or 0)
    sig = tool_call_signature(name, args)
    _RECENT_TOOL_CALLS.append(sig)
    if max_reps <= 0 or len(_RECENT_TOOL_CALLS) < max_reps:
        return None
    if not all(s == sig for s in _RECENT_TOOL_CALLS[-max_reps:]):
        return None
    return format_actionable_error(
        CATEGORY_LOOP_REJECTED,
        tool=name,
        detail=(
            f"Called {name} with the same arguments {max_reps} times in a row; "
            "the result will not change."
        ),
    )


def check_path_read_budget(name: str, args: Any) -> Optional[str]:
    """Reject further reads of the same path after the per-turn budget is spent.

    Catches sliding-window ``cat_file`` / range hunting that never trips the
    exact-arg loop detector because each range looks like a new call.
    """
    if name not in READ_BUDGET_TOOLS:
        return None
    limit = int(getattr(config, "MAX_PATH_READS_PER_TURN", 6) or 0)
    if limit <= 0:
        return None
    path = _path_from_args(args)
    if not path:
        return None

    count = _PATH_READ_COUNTS.get(path, 0) + 1
    _PATH_READ_COUNTS[path] = count
    if count <= limit:
        return None

    try:
        config.SESSION_READ_BUDGET_TRIPS = int(
            getattr(config, "SESSION_READ_BUDGET_TRIPS", 0) or 0
        ) + 1
    except Exception:
        logger.debug("Failed to increment SESSION_READ_BUDGET_TRIPS", exc_info=True)

    return format_actionable_error(
        CATEGORY_READ_BUDGET,
        tool=name,
        detail=(
            f"Already read {path!r} {count - 1} times this turn "
            f"(limit {limit}) with varying ranges/args."
        ),
        path=path,
    )


def check_tool_guards(name: Optional[str], args: Any) -> Optional[str]:
    """Run path-read and exact-repeat guards. Return rejection message or None."""
    if not isinstance(name, str) or not name:
        return None
    read_reject = check_path_read_budget(name, args)
    if read_reject:
        return read_reject
    return check_exact_repeat(name, args)


def categorize_failure(
    *,
    tool: Optional[str] = None,
    error: Any = None,
    result: Any = None,
) -> str:
    """Map a tool error/result to a failure category."""
    text_parts = []
    if error is not None:
        text_parts.append(str(error))
    if isinstance(result, dict):
        if result.get("ok") is False and result.get("error"):
            text_parts.append(str(result.get("error")))
        elif result.get("error"):
            text_parts.append(str(result.get("error")))
    elif result is not None and not isinstance(result, dict):
        text_parts.append(str(result))
    text = " ".join(text_parts).lower()

    if not text.strip():
        return CATEGORY_UNKNOWN

    if "loop detected" in text or "same arguments" in text:
        return CATEGORY_LOOP_REJECTED
    if "already read" in text and "this turn" in text:
        return CATEGORY_READ_BUDGET
    if "permission denied" in text or "operation not permitted" in text:
        return CATEGORY_PERMISSION_DENIED
    if "string not found" in text or "matches 0 times" in text:
        return CATEGORY_MISSING_MATCH
    if "matches" in text and "times" in text and "exactly one" in text:
        return CATEGORY_MISSING_MATCH
    if "not found in" in text and ("string" in text or "old_str" in text):
        return CATEGORY_MISSING_MATCH
    if "oversized" in text or "token limit" in text or "too large" in text:
        return CATEGORY_OVERSIZED_OUTPUT
    if "context" in text and (
        "length" in text or "window" in text or "overflow" in text or "exceed" in text
    ):
        return CATEGORY_CONTEXT_PRESSURE
    if re.search(r"\b(401|403|429|500|502|503|rate.?limit|timeout|api error)\b", text):
        return CATEGORY_PROVIDER_ERROR
    if tool in {"run_python_tests", "type_check_python"} or "failed" in text and "test" in text:
        if "traceback" in text or "assertion" in text or "failed" in text:
            return CATEGORY_TEST_FAILURE
    if (
        "invalid" in text
        or "required" in text
        or "missing" in text and "argument" in text
        or "must be" in text
        or "parsing arguments" in text
        or "typeerror" in text
    ):
        return CATEGORY_INVALID_ARGUMENTS
    if "file not found" in text or "does not exist" in text:
        return CATEGORY_INVALID_ARGUMENTS
    if "permission" in text or "read-only" in text:
        return CATEGORY_PERMISSION_DENIED

    return CATEGORY_UNKNOWN


def format_actionable_error(
    category: str,
    *,
    tool: Optional[str] = None,
    detail: str = "",
    path: Optional[str] = None,
) -> str:
    """Build a concise model-facing error with one recovery step."""
    recovery = _RECOVERY.get(category, _RECOVERY[CATEGORY_UNKNOWN])
    parts = [f"[{category}]"]
    if tool:
        parts.append(f"{tool}:")
    if detail:
        parts.append(detail.rstrip("."))
    elif path:
        parts.append(f"Failed for {path}")
    parts.append(f"Recovery: {recovery}")
    return " ".join(parts)


def enrich_tool_failure(
    tool: Optional[str],
    error: Any = None,
    result: Any = None,
) -> Tuple[Any, Any]:
    """Rewrite error/result payloads with categorized, actionable messages.

    Returns ``(result, error)``. Dict results with ``ok: False`` get an enriched
    ``error`` field and keep other keys. String errors are replaced entirely.
    Detailed originals stay in logs via the caller.
    """
    category = categorize_failure(tool=tool, error=error, result=result)

    if isinstance(result, dict) and result.get("ok") is False:
        raw = str(result.get("error") or error or "edit failed")
        logger.info(
            "[TOOL_FAILURE] category=%s tool=%s detail=%s",
            category,
            tool,
            raw[:500],
        )
        enriched = dict(result)
        enriched["error"] = format_actionable_error(
            category,
            tool=tool,
            detail=raw,
            path=result.get("path") or result.get("file"),
        )
        enriched["failure_category"] = category
        return enriched, error

    if error:
        raw = str(error)
        logger.info(
            "[TOOL_FAILURE] category=%s tool=%s detail=%s",
            category,
            tool,
            raw[:500],
        )
        return result, format_actionable_error(category, tool=tool, detail=raw)

    if isinstance(result, str) and result and categorize_failure(tool=tool, result=result) != CATEGORY_UNKNOWN:
        # String results that are already failure messages (e.g. modify_source_code).
        cat = categorize_failure(tool=tool, result=result)
        if cat != CATEGORY_UNKNOWN:
            logger.info(
                "[TOOL_FAILURE] category=%s tool=%s detail=%s",
                cat,
                tool,
                result[:500],
            )
            return format_actionable_error(cat, tool=tool, detail=result), error

    return result, error


def record_edit_tool_usage(tool: Optional[str]) -> None:
    """Count deterministic vs NL edit tool invocations; notice NL fallback once/turn."""
    global _NL_FALLBACK_NOTICED_THIS_TURN
    if not isinstance(tool, str) or not tool:
        return
    try:
        if tool in DETERMINISTIC_EDIT_TOOLS:
            config.SESSION_DETERMINISTIC_EDIT_COUNT = int(
                getattr(config, "SESSION_DETERMINISTIC_EDIT_COUNT", 0) or 0
            ) + 1
        elif tool in NL_EDIT_TOOLS:
            config.SESSION_NL_EDIT_COUNT = int(
                getattr(config, "SESSION_NL_EDIT_COUNT", 0) or 0
            ) + 1
            if not _NL_FALLBACK_NOTICED_THIS_TURN:
                _NL_FALLBACK_NOTICED_THIS_TURN = True
                print(
                    "[notice] Using modify_source_code (natural-language fallback). "
                    "Prefer text_file_create / text_file_str_replace_in_file / "
                    "text_file_insert_text_at_line / bulk_replace_in_files when the "
                    "change can be expressed as exact text."
                )
    except Exception:
        logger.debug("Failed to record edit-tool usage", exc_info=True)


def preferred_edit_order_text() -> str:
    """Human-readable preferred edit order for docs and help."""
    return " → ".join(PREFERRED_EDIT_ORDER)
