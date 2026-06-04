"""Aggregate a run JSON (produced by runner.py) into a human-readable summary.

The runner writes raw per-sample results to results/run-<timestamp>.json.
This module turns that into a markdown table you can paste into a PR or
diff against a previous run.

Two views by default:

    Per task   — passes/N, avg cost USD, avg tool calls, avg loop trips
    Per tag    — same metrics rolled up by tag (e.g. "memory", "todo")

Numbers are averaged across SAMPLES that produced a metrics JSON; samples
that crashed before :dump_metrics fired show up in pass-rate but are
excluded from cost/tool averages (the floor of "$0 because no metrics"
would otherwise look better than a partial run).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_mean(values: List[float]) -> Optional[float]:
    """Mean of a list, or None if empty — used to distinguish "metric was
    zero" from "no data" in the rendered table."""
    return statistics.fmean(values) if values else None


def _fmt_money(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"${v:.4f}"


def _fmt_int(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:.1f}"


def _fmt_pct(passes: int, n: int) -> str:
    return f"{passes}/{n} ({(passes / n * 100) if n else 0:.0f}%)"


def aggregate(run_json: Dict[str, Any]) -> Dict[str, Any]:
    """Compute per-task and per-tag summaries from a raw run dict."""
    results: List[Dict[str, Any]] = run_json.get("results", []) or []

    by_task: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_tag: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_task[r["task"]].append(r)
        for tag in r.get("tags") or []:
            by_tag[tag].append(r)

    def _summarize(group: List[Dict[str, Any]]) -> Dict[str, Any]:
        n = len(group)
        passes = sum(1 for r in group if r.get("passed"))
        metrics = [r.get("metrics") for r in group if r.get("metrics")]
        costs = [m.get("session_cost_usd", 0.0) for m in metrics if m is not None]
        tool_calls = [m.get("session_tool_call_count", 0) for m in metrics if m is not None]
        loop_trips = [m.get("session_loop_detector_trips", 0) for m in metrics if m is not None]
        tokens = [m.get("session_total_tokens", 0) for m in metrics if m is not None]
        durations = [r.get("duration_seconds", 0.0) for r in group]
        return {
            "n": n,
            "passes": passes,
            "pass_rate": (passes / n) if n else 0.0,
            "avg_cost_usd": _safe_mean(costs),
            "avg_tool_calls": _safe_mean(tool_calls),
            "avg_loop_trips": _safe_mean(loop_trips),
            "avg_tokens": _safe_mean(tokens),
            "avg_duration_seconds": _safe_mean(durations),
            "samples_with_metrics": len(metrics),
        }

    per_task = {name: _summarize(group) for name, group in sorted(by_task.items())}
    per_tag = {name: _summarize(group) for name, group in sorted(by_tag.items())}
    overall = _summarize(results)
    return {
        "model": run_json.get("model"),
        "samples_per_task": run_json.get("samples_per_task"),
        "task_filter": run_json.get("task_filter"),
        "started_at": run_json.get("started_at"),
        "finished_at": run_json.get("finished_at"),
        "overall": overall,
        "per_task": per_task,
        "per_tag": per_tag,
    }


def render_markdown(summary: Dict[str, Any]) -> str:
    """Markdown summary suitable for pasting into a PR description."""
    lines: List[str] = []
    overall = summary["overall"]
    lines.append("# monitor_bench run")
    lines.append("")
    lines.append(f"- Model: `{summary.get('model') or '(monitor default)'}`")
    lines.append(f"- Samples per task: {summary.get('samples_per_task')}")
    if summary.get("task_filter"):
        lines.append(f"- Task filter: `{summary['task_filter']}`")
    duration = (summary.get("finished_at") or 0) - (summary.get("started_at") or 0)
    lines.append(f"- Wall clock: {duration:.1f}s")
    lines.append("")
    lines.append(
        f"**Overall: {_fmt_pct(overall['passes'], overall['n'])} — "
        f"avg cost {_fmt_money(overall['avg_cost_usd'])}, "
        f"avg tool calls {_fmt_int(overall['avg_tool_calls'])}, "
        f"avg loop trips {_fmt_int(overall['avg_loop_trips'])}**"
    )
    lines.append("")
    lines.append("## Per task")
    lines.append("")
    lines.append("| Task | Pass | Avg cost | Avg tool calls | Avg loop trips | Avg duration |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for task_name, summ in summary["per_task"].items():
        lines.append(
            f"| {task_name} "
            f"| {_fmt_pct(summ['passes'], summ['n'])} "
            f"| {_fmt_money(summ['avg_cost_usd'])} "
            f"| {_fmt_int(summ['avg_tool_calls'])} "
            f"| {_fmt_int(summ['avg_loop_trips'])} "
            f"| {_fmt_int(summ['avg_duration_seconds'])}s |"
        )
    if summary["per_tag"]:
        lines.append("")
        lines.append("## Per tag")
        lines.append("")
        lines.append("| Tag | Pass | Avg cost | Avg tool calls | Avg loop trips |")
        lines.append("|---|---|---:|---:|---:|")
        for tag, summ in summary["per_tag"].items():
            lines.append(
                f"| {tag} "
                f"| {_fmt_pct(summ['passes'], summ['n'])} "
                f"| {_fmt_money(summ['avg_cost_usd'])} "
                f"| {_fmt_int(summ['avg_tool_calls'])} "
                f"| {_fmt_int(summ['avg_loop_trips'])} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Render a monitor_bench run as a markdown summary.")
    parser.add_argument("run_json", type=Path, help="Path to a results/run-*.json file.")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Where to write the markdown. Default: stdout.",
    )
    args = parser.parse_args(argv)
    run = json.loads(args.run_json.read_text())
    summary = aggregate(run)
    md = render_markdown(summary)
    if args.out:
        args.out.write_text(md)
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
