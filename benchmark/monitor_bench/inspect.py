"""Inspect a monitor_bench run JSON for quick post-run debugging.

This helper turns the raw results JSON into a concise human-readable summary,
with emphasis on failed samples. It is intentionally complementary to
report.py: report.py gives aggregate markdown tables, while this module helps a
developer answer "why did this specific sample fail?" without manually opening
and spelunking through the full JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _final_assistant_text(history: Optional[List[Dict[str, Any]]]) -> str:
    """Return the last assistant message content, or an empty string."""
    if not history:
        return ""
    for message in reversed(history):
        if message.get("role") == "assistant":
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
    return ""


def _truncate(text: str, limit: int) -> str:
    """Return text truncated to ``limit`` characters, preserving readability."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _matches_task(result: Dict[str, Any], task: Optional[str]) -> bool:
    """True when the sample matches the optional task filter."""
    if not task:
        return True
    return result.get("task") == task


def _matches_failed_only(result: Dict[str, Any], failed_only: bool) -> bool:
    """True when the sample matches the failed-only filter."""
    if not failed_only:
        return True
    return not bool(result.get("passed"))


def _format_metrics(metrics: Optional[Dict[str, Any]]) -> str:
    """Render a compact metrics summary for one sample."""
    if not metrics:
        return "(no metrics)"
    cost = metrics.get("session_cost_usd")
    tool_calls = metrics.get("session_tool_call_count")
    loop_trips = metrics.get("session_loop_detector_trips")
    tokens = metrics.get("session_total_tokens")
    return (
        f"cost={cost!r}, tool_calls={tool_calls!r}, "
        f"loop_trips={loop_trips!r}, total_tokens={tokens!r}"
    )


def inspect_run(
    run_json: Dict[str, Any],
    *,
    failed_only: bool = False,
    task: Optional[str] = None,
    show_history: bool = False,
    text_limit: int = 1200,
) -> str:
    """Return a human-readable post-run inspection report.

    Args:
        run_json: Parsed benchmark run JSON.
        failed_only: When True, include only failed samples.
        task: Optional exact task-name filter.
        show_history: When True, include the full serialized conversation
            history for each included sample.
        text_limit: Maximum characters to show for long free-text sections.

    Returns:
        A formatted multi-line string.
    """
    results = run_json.get("results", []) or []
    included = [
        result for result in results
        if _matches_task(result, task) and _matches_failed_only(result, failed_only)
    ]

    total = len(results)
    passes = sum(1 for result in results if result.get("passed"))

    lines: List[str] = []
    lines.append("# monitor_bench inspect")
    lines.append("")
    lines.append(f"model: {run_json.get('model') or '(monitor default)'}")
    lines.append(f"samples_per_task: {run_json.get('samples_per_task')}")
    lines.append(f"overall: {passes}/{total} passed")
    lines.append(f"included samples: {len(included)}")
    lines.append("")

    if not included:
        lines.append("No matching samples.")
        return "\n".join(lines) + "\n"

    for result in included:
        lines.append("=" * 80)
        lines.append(f"task: {result.get('task')}")
        lines.append(f"sample: {result.get('sample')}")
        lines.append(f"passed: {result.get('passed')}")
        lines.append(f"detail: {result.get('detail')}")
        lines.append(f"exit_code: {result.get('exit_code')}")
        lines.append(f"timed_out: {result.get('timed_out')}")
        lines.append(f"duration_seconds: {result.get('duration_seconds')}")
        lines.append(f"metrics: {_format_metrics(result.get('metrics'))}")

        history = result.get("conversation_history")
        history_len = len(history) if isinstance(history, list) else None
        lines.append(f"history_length: {history_len!r}")

        final = _final_assistant_text(history)
        if final:
            lines.append("final_assistant:")
            lines.append(_truncate(final, text_limit))

        stderr_tail = result.get("stderr_tail") or ""
        if stderr_tail:
            lines.append("stderr_tail:")
            lines.append(_truncate(str(stderr_tail), text_limit))

        error = result.get("error") or ""
        if error:
            lines.append("error:")
            lines.append(_truncate(str(error), text_limit))

        if show_history and history is not None:
            lines.append("conversation_history:")
            lines.append(_truncate(json.dumps(history, indent=2, ensure_ascii=False), text_limit))

        lines.append("")

    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for benchmark run inspection."""
    parser = argparse.ArgumentParser(
        description="Inspect a monitor_bench run JSON for per-sample failure details."
    )
    parser.add_argument("run_json", type=Path, help="Path to a results/run-*.json file.")
    parser.add_argument(
        "--failed-only",
        action="store_true",
        help="Show only failed samples.",
    )
    parser.add_argument(
        "--task",
        type=str,
        default=None,
        help="Filter to one exact task name.",
    )
    parser.add_argument(
        "--show-history",
        action="store_true",
        help="Include serialized conversation_history for each included sample.",
    )
    parser.add_argument(
        "--text-limit",
        type=int,
        default=1200,
        help="Character limit for long text sections (default: 1200).",
    )
    args = parser.parse_args(argv)

    run = json.loads(args.run_json.read_text())
    output = inspect_run(
        run,
        failed_only=args.failed_only,
        task=args.task,
        show_history=args.show_history,
        text_limit=args.text_limit,
    )
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
