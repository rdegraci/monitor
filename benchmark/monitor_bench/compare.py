"""Compare two monitor_bench run JSON files.

This helper is a post-processing utility for benchmark users. It compares two
raw run JSON files produced by ``benchmark.monitor_bench.runner`` and renders a
terminal-friendly summary of what improved, regressed, stayed unchanged, or was
added/removed at the task level.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from benchmark.monitor_bench.report import aggregate

MetricName = Literal["pass", "cost", "tools", "loops", "duration"]
Classification = Literal["improvement", "regression", "mixed", "unchanged"]
OutputFormat = Literal["text", "markdown", "json"]
_EPSILON = 1e-9


@dataclass(frozen=True)
class CompareThresholds:
    """Threshold configuration for compare semantics.

    Attributes:
        pass_rate: Minimum absolute pass-rate delta required to classify a
            pass-rate change as improved or regressed.
        cost: Minimum absolute cost delta required to classify a cost change as
            improved or regressed.
        tools: Minimum absolute tool-call delta required to classify a tool-call
            change as improved or regressed.
        loops: Minimum absolute loop-trip delta required to classify a loop-trip
            change as improved or regressed.
        duration: Minimum absolute duration delta required to classify a
            duration change as improved or regressed.
    """

    pass_rate: float = 1e-9
    cost: float = 0.0
    tools: float = 0.0
    loops: float = 0.0
    duration: float = 0.0


@dataclass(frozen=True)
class MetricDelta:
    """One metric's before/after values and directional interpretation."""

    label: str
    before: Optional[float]
    after: Optional[float]
    lower_is_better: bool


@dataclass(frozen=True)
class TaskComparison:
    """Comparison details for one benchmark task."""

    task: str
    before: Optional[Dict[str, Any]]
    after: Optional[Dict[str, Any]]
    classification: Classification
    metrics: Tuple[MetricDelta, ...]


@dataclass(frozen=True)
class VisibleCompareContext:
    """Visible compare context derived from filters and sorting."""

    tasks: List[TaskComparison]
    grouped_tasks: Dict[str, List[TaskComparison]]
    missing_tasks: List[str]
    new_tasks: List[str]


def _metric_threshold(label: str, thresholds: CompareThresholds) -> float:
    """Return the configured comparison threshold for a metric.

    Args:
        label: Metric label from :class:`MetricDelta`.
        thresholds: Active comparison thresholds.

    Returns:
        Threshold value associated with ``label``.
    """
    mapping = {
        "pass": thresholds.pass_rate,
        "cost": thresholds.cost,
        "tools": thresholds.tools,
        "loops": thresholds.loops,
        "duration": thresholds.duration,
    }
    return mapping[label]


def _thresholds_are_default(thresholds: CompareThresholds) -> bool:
    """Return whether thresholds match the default compare configuration.

    Args:
        thresholds: Active comparison thresholds.

    Returns:
        ``True`` when the thresholds equal :class:`CompareThresholds()` exactly.
    """
    return thresholds == CompareThresholds()


def _format_threshold_value(value: float) -> str:
    """Format one threshold value for human-readable output.

    Args:
        value: Threshold value to format.

    Returns:
        Compact decimal representation suitable for report output.
    """
    return format(value, ".12g")


def _append_threshold_lines(lines: List[str], thresholds: CompareThresholds) -> None:
    """Append threshold display lines to a text report.

    Args:
        lines: Mutable list of report lines to extend.
        thresholds: Active comparison thresholds.
    """
    lines.append("Thresholds")
    lines.append("----------")
    lines.append(f"Pass rate:    {_format_threshold_value(thresholds.pass_rate)}")
    lines.append(f"Cost:         {_format_threshold_value(thresholds.cost)}")
    lines.append(f"Tool calls:   {_format_threshold_value(thresholds.tools)}")
    lines.append(f"Loops:        {_format_threshold_value(thresholds.loops)}")
    lines.append(f"Duration:     {_format_threshold_value(thresholds.duration)}")


def _append_threshold_markdown_lines(lines: List[str], thresholds: CompareThresholds) -> None:
    """Append threshold display lines to a markdown report.

    Args:
        lines: Mutable list of report lines to extend.
        thresholds: Active comparison thresholds.
    """
    lines.append("## Active thresholds")
    lines.append("")
    lines.append(f"- **Pass rate:** `{_format_threshold_value(thresholds.pass_rate)}`")
    lines.append(f"- **Cost:** `{_format_threshold_value(thresholds.cost)}`")
    lines.append(f"- **Tool calls:** `{_format_threshold_value(thresholds.tools)}`")
    lines.append(f"- **Loops:** `{_format_threshold_value(thresholds.loops)}`")
    lines.append(f"- **Duration:** `{_format_threshold_value(thresholds.duration)}`")


def _serialize_thresholds(thresholds: CompareThresholds) -> Dict[str, float]:
    """Serialize threshold configuration for machine-readable output.

    Args:
        thresholds: Active comparison thresholds.

    Returns:
        Dictionary of threshold values keyed by metric family.
    """
    return {
        "pass_rate": thresholds.pass_rate,
        "cost": thresholds.cost,
        "tools": thresholds.tools,
        "loops": thresholds.loops,
        "duration": thresholds.duration,
    }


def _classify_metric(
    delta: MetricDelta,
    thresholds: CompareThresholds = CompareThresholds(),
) -> Optional[str]:
    """Return the metric-level direction label when both values are present.

    Args:
        delta: Metric values and whether lower numbers are preferable.
        thresholds: Active comparison thresholds.

    Returns:
        ``"improvement"``, ``"regression"``, or ``None`` when the values are
        effectively unchanged or cannot be compared.
    """
    if delta.before is None or delta.after is None:
        return None
    threshold = _metric_threshold(delta.label, thresholds)
    if abs(delta.after - delta.before) <= max(threshold, _EPSILON):
        return None
    if delta.lower_is_better:
        return "improvement" if delta.after < delta.before else "regression"
    return "improvement" if delta.after > delta.before else "regression"


def _build_metric_deltas(
    before: Optional[Dict[str, Any]],
    after: Optional[Dict[str, Any]],
) -> Tuple[MetricDelta, ...]:
    """Build the standard compare metric list for one summary pair.

    Args:
        before: Aggregated summary dictionary from the baseline run.
        after: Aggregated summary dictionary from the candidate run.

    Returns:
        Tuple of metric deltas in display order.
    """
    before_pass = None if before is None else before.get("pass_rate")
    after_pass = None if after is None else after.get("pass_rate")
    before_cost = None if before is None else before.get("avg_cost_usd")
    after_cost = None if after is None else after.get("avg_cost_usd")
    before_tools = None if before is None else before.get("avg_tool_calls")
    after_tools = None if after is None else after.get("avg_tool_calls")
    before_loops = None if before is None else before.get("avg_loop_trips")
    after_loops = None if after is None else after.get("avg_loop_trips")
    before_duration = None if before is None else before.get("avg_duration_seconds")
    after_duration = None if after is None else after.get("avg_duration_seconds")
    return (
        MetricDelta("pass", before_pass, after_pass, lower_is_better=False),
        MetricDelta("cost", before_cost, after_cost, lower_is_better=True),
        MetricDelta("tools", before_tools, after_tools, lower_is_better=True),
        MetricDelta("loops", before_loops, after_loops, lower_is_better=True),
        MetricDelta("duration", before_duration, after_duration, lower_is_better=True),
    )


def _classify_summary(
    before: Optional[Dict[str, Any]],
    after: Optional[Dict[str, Any]],
    thresholds: CompareThresholds = CompareThresholds(),
) -> Classification:
    """Classify a before/after summary pair.

    Args:
        before: Aggregated summary dictionary from the baseline run.
        after: Aggregated summary dictionary from the candidate run.
        thresholds: Active comparison thresholds.

    Returns:
        High-level comparison classification.
    """
    if before is None or after is None:
        return "mixed"

    deltas = _build_metric_deltas(before, after)
    pass_outcome = _classify_metric(deltas[0], thresholds)
    efficiency_outcomes = [
        outcome for outcome in (_classify_metric(delta, thresholds) for delta in deltas[1:]) if outcome is not None
    ]
    improvements = efficiency_outcomes.count("improvement")
    regressions = efficiency_outcomes.count("regression")

    if pass_outcome == "improvement":
        if regressions and not improvements:
            return "mixed"
        return "improvement"
    if pass_outcome == "regression":
        return "regression"

    if improvements and regressions:
        return "mixed"
    if regressions:
        return "regression"
    if improvements:
        return "improvement"
    return "unchanged"


def compare_runs(
    before_run: Dict[str, Any],
    after_run: Dict[str, Any],
    thresholds: CompareThresholds = CompareThresholds(),
) -> Dict[str, Any]:
    """Compare two raw benchmark run dictionaries.

    Args:
        before_run: Parsed run JSON representing the baseline behavior.
        after_run: Parsed run JSON representing the candidate behavior.
        thresholds: Active comparison thresholds.

    Returns:
        Dictionary containing the aggregated summaries and per-task comparisons.
    """
    before_summary = aggregate(before_run)
    after_summary = aggregate(after_run)
    before_tasks = before_summary["per_task"]
    after_tasks = after_summary["per_task"]

    task_names = sorted(set(before_tasks) | set(after_tasks))
    task_comparisons: List[TaskComparison] = []
    missing_tasks: List[str] = []
    new_tasks: List[str] = []
    for task_name in task_names:
        before_task = before_tasks.get(task_name)
        after_task = after_tasks.get(task_name)
        if before_task is None:
            new_tasks.append(task_name)
            continue
        if after_task is None:
            missing_tasks.append(task_name)
            continue
        task_comparisons.append(
            TaskComparison(
                task=task_name,
                before=before_task,
                after=after_task,
                classification=_classify_summary(before_task, after_task, thresholds),
                metrics=_build_metric_deltas(before_task, after_task),
            )
        )

    overall_metrics = _build_metric_deltas(before_summary["overall"], after_summary["overall"])
    return {
        "before_summary": before_summary,
        "after_summary": after_summary,
        "overall_classification": _classify_summary(
            before_summary["overall"],
            after_summary["overall"],
            thresholds,
        ),
        "overall_metrics": overall_metrics,
        "tasks": task_comparisons,
        "missing_tasks": missing_tasks,
        "new_tasks": new_tasks,
        "thresholds": thresholds,
    }


def _fmt_money(value: Optional[float]) -> str:
    """Format a currency metric for compare output."""
    if value is None:
        return "—"
    return f"${value:.4f}"


def _fmt_count(value: Optional[float]) -> str:
    """Format a count-like metric for compare output."""
    if value is None:
        return "—"
    return f"{value:.1f}"


def _fmt_duration(value: Optional[float]) -> str:
    """Format a duration metric for compare output."""
    if value is None:
        return "—"
    return f"{value:.1f}s"


def _fmt_pass_summary(summary: Dict[str, Any]) -> str:
    """Format pass count and pass rate for one aggregated summary."""
    n = summary.get("n", 0)
    passes = summary.get("passes", 0)
    pct = (passes / n * 100.0) if n else 0.0
    return f"{passes}/{n} ({pct:.0f}%)"


def _fmt_metric_value(label: str, value: Optional[float]) -> str:
    """Format one metric value according to its metric type."""
    if label == "cost":
        return _fmt_money(value)
    if label in {"tools", "loops"}:
        return _fmt_count(value)
    if label == "duration":
        return _fmt_duration(value)
    if value is None:
        return "—"
    return f"{value:.3f}"


def _label_text(classification: Classification) -> str:
    """Return the display label for a classification."""
    return classification.upper()


def _overall_metric_display_label(label: str) -> str:
    """Return the display label for one overall metric.

    Args:
        label: Metric label from :class:`MetricDelta`.

    Returns:
        Human-readable metric label used in report output.
    """
    mapping = {
        "cost": "Avg cost",
        "tools": "Avg tool calls",
        "loops": "Avg loops",
        "duration": "Avg duration",
    }
    return mapping[label]


def _task_metric_display_label(label: str) -> str:
    """Return the display label for one task metric.

    Args:
        label: Metric label from :class:`MetricDelta`.

    Returns:
        Human-readable metric label used in task sections.
    """
    mapping = {
        "cost": "Cost",
        "tools": "Tools",
        "loops": "Loops",
        "duration": "Duration",
    }
    return mapping[label]


def _metric_sort_value(task: TaskComparison, sort_by: MetricName) -> float:
    """Return a sort key where larger values mean more changed/worse for display.

    Args:
        task: Per-task comparison record.
        sort_by: Metric family chosen by the CLI.

    Returns:
        Floating-point sort key used in descending order.
    """
    if task.before is None or task.after is None:
        return float("-inf")
    if sort_by == "pass":
        before_value = task.before.get("pass_rate") or 0.0
        after_value = task.after.get("pass_rate") or 0.0
        return abs(after_value - before_value)
    mapping = {
        "cost": "avg_cost_usd",
        "tools": "avg_tool_calls",
        "loops": "avg_loop_trips",
        "duration": "avg_duration_seconds",
    }
    field = mapping[sort_by]
    before_value = task.before.get(field)
    after_value = task.after.get(field)
    if before_value is None or after_value is None:
        return -1.0
    return abs(after_value - before_value)


def _matches_filters(
    task: TaskComparison,
    *,
    only_regressions: bool,
    only_improvements: bool,
    show_unchanged: bool,
    task_name: Optional[str],
) -> bool:
    """Return whether a task comparison should be shown.

    Args:
        task: Per-task comparison record.
        only_regressions: Keep only regressions.
        only_improvements: Keep only improvements.
        show_unchanged: Include unchanged tasks.
        task_name: Optional exact task filter.

    Returns:
        ``True`` when the task should be rendered.
    """
    if task_name and task.task != task_name:
        return False
    if only_regressions:
        return task.classification == "regression"
    if only_improvements:
        return task.classification == "improvement"
    if task.classification == "unchanged":
        return show_unchanged
    return True


def _get_visible_tasks(
    comparison: Dict[str, Any],
    *,
    only_regressions: bool,
    only_improvements: bool,
    show_unchanged: bool,
    task_name: Optional[str],
    sort_by: MetricName,
) -> List[TaskComparison]:
    """Return filtered and sorted task comparisons for display.

    Args:
        comparison: Output from :func:`compare_runs`.
        only_regressions: Include only regression tasks.
        only_improvements: Include only improvement tasks.
        show_unchanged: Include unchanged tasks.
        task_name: Optional exact task-name filter.
        sort_by: Metric family used for task sorting.

    Returns:
        List of visible task comparisons in display order.
    """
    return [
        task
        for task in sorted(
            comparison["tasks"],
            key=lambda item: (_metric_sort_value(item, sort_by), item.task),
            reverse=True,
        )
        if _matches_filters(
            task,
            only_regressions=only_regressions,
            only_improvements=only_improvements,
            show_unchanged=show_unchanged,
            task_name=task_name,
        )
    ]


def _group_tasks_by_classification(
    tasks: List[TaskComparison],
) -> Dict[str, List[TaskComparison]]:
    """Group task comparisons by classification.

    Args:
        tasks: Visible task comparisons.

    Returns:
        Mapping from classification to task list.
    """
    grouped: Dict[str, List[TaskComparison]] = {
        "regression": [],
        "improvement": [],
        "mixed": [],
        "unchanged": [],
    }
    for task in tasks:
        grouped[task.classification].append(task)
    return grouped


def _get_visible_missing_new_tasks(
    comparison: Dict[str, Any],
    *,
    task_name: Optional[str],
) -> Tuple[List[str], List[str]]:
    """Return visible missing and new task names.

    Args:
        comparison: Output from :func:`compare_runs`.
        task_name: Optional exact task-name filter.

    Returns:
        Tuple of ``(missing_tasks, new_tasks)`` after filtering.
    """
    missing_tasks = comparison["missing_tasks"]
    new_tasks = comparison["new_tasks"]
    if task_name:
        missing_tasks = [name for name in missing_tasks if name == task_name]
        new_tasks = [name for name in new_tasks if name == task_name]
    return missing_tasks, new_tasks


def _build_visible_compare_context(
    comparison: Dict[str, Any],
    *,
    only_regressions: bool,
    only_improvements: bool,
    show_unchanged: bool,
    task_name: Optional[str],
    sort_by: MetricName,
) -> VisibleCompareContext:
    """Build the visible compare context used by renderers.

    Args:
        comparison: Output from :func:`compare_runs`.
        only_regressions: Include only regression tasks.
        only_improvements: Include only improvement tasks.
        show_unchanged: Include unchanged tasks.
        task_name: Optional exact task-name filter.
        sort_by: Metric family used for task sorting.

    Returns:
        Visible compare context including tasks, grouped tasks, and missing/new
        task names after filtering.
    """
    tasks = _get_visible_tasks(
        comparison,
        only_regressions=only_regressions,
        only_improvements=only_improvements,
        show_unchanged=show_unchanged,
        task_name=task_name,
        sort_by=sort_by,
    )
    missing_tasks, new_tasks = _get_visible_missing_new_tasks(
        comparison,
        task_name=task_name,
    )
    return VisibleCompareContext(
        tasks=tasks,
        grouped_tasks=_group_tasks_by_classification(tasks),
        missing_tasks=missing_tasks,
        new_tasks=new_tasks,
    )


def _serialize_metric_delta(
    delta: MetricDelta,
    thresholds: CompareThresholds = CompareThresholds(),
) -> Dict[str, Any]:
    """Serialize one metric delta for machine-readable output.

    Args:
        delta: Metric delta to serialize.
        thresholds: Active comparison thresholds.

    Returns:
        Dictionary containing metric fields and classification.
    """
    classification = _classify_metric(delta, thresholds)
    return {
        "label": delta.label,
        "before": delta.before,
        "after": delta.after,
        "lower_is_better": delta.lower_is_better,
        "threshold": _metric_threshold(delta.label, thresholds),
        "classification": "unchanged" if classification is None else classification,
    }


def _serialize_task_comparison(
    task: TaskComparison,
    thresholds: CompareThresholds = CompareThresholds(),
) -> Dict[str, Any]:
    """Serialize one task comparison for machine-readable output.

    Args:
        task: Task comparison to serialize.
        thresholds: Active comparison thresholds.

    Returns:
        Dictionary containing task comparison details.
    """
    result: Dict[str, Any] = {
        "task": task.task,
        "before": task.before,
        "after": task.after,
        "classification": task.classification,
        "metrics": [_serialize_metric_delta(delta, thresholds) for delta in task.metrics],
    }
    if task.before is not None and task.after is not None:
        result["before_pass_summary"] = _fmt_pass_summary(task.before)
        result["after_pass_summary"] = _fmt_pass_summary(task.after)
    return result


def render_compare_report(
    comparison: Dict[str, Any],
    *,
    before_path: str,
    after_path: str,
    only_regressions: bool = False,
    only_improvements: bool = False,
    task_name: Optional[str] = None,
    show_unchanged: bool = False,
    sort_by: MetricName = "pass",
    thresholds: CompareThresholds = CompareThresholds(),
) -> str:
    """Render a terminal-friendly compare report.

    Args:
        comparison: Output from :func:`compare_runs`.
        before_path: Baseline run path for the report header.
        after_path: Candidate run path for the report header.
        only_regressions: Include only regression tasks.
        only_improvements: Include only improvement tasks.
        task_name: Optional exact task-name filter.
        show_unchanged: Include unchanged tasks.
        sort_by: Metric family used for task sorting.
        thresholds: Active comparison thresholds.

    Returns:
        Formatted multi-line compare report.
    """
    lines: List[str] = []
    lines.append("# monitor_bench compare")
    lines.append("")
    lines.append(f"Before: {before_path}")
    lines.append(f"After:  {after_path}")
    if not _thresholds_are_default(thresholds):
        lines.append("")
        _append_threshold_lines(lines, thresholds)
    lines.append("")
    lines.append("Overall")
    lines.append("-------")

    before_overall = comparison["before_summary"]["overall"]
    after_overall = comparison["after_summary"]["overall"]
    lines.append(
        f"Pass rate:      {_fmt_pass_summary(before_overall)} -> {_fmt_pass_summary(after_overall)} "
        f"[{_label_text(comparison['overall_classification'])}]"
    )
    for delta in comparison["overall_metrics"][1:]:
        label = _overall_metric_display_label(delta.label)
        lines.append(
            f"{label + ':':<15} {_fmt_metric_value(delta.label, delta.before)} -> "
            f"{_fmt_metric_value(delta.label, delta.after)} "
            f"[{_label_text(_classify_metric(delta, thresholds) or 'unchanged')}]"
        )

    visible_context = _build_visible_compare_context(
        comparison,
        only_regressions=only_regressions,
        only_improvements=only_improvements,
        show_unchanged=show_unchanged,
        task_name=task_name,
        sort_by=sort_by,
    )

    for classification, title in (
        ("regression", "Regressions"),
        ("improvement", "Improvements"),
        ("mixed", "Mixed changes"),
        ("unchanged", "Unchanged"),
    ):
        items = visible_context.grouped_tasks[classification]
        if classification == "unchanged" and not show_unchanged:
            continue
        lines.append("")
        lines.append(title)
        lines.append("-" * len(title))
        if not items:
            lines.append("(none)")
            continue
        for task in items:
            lines.append(f"{task.task} [{_label_text(task.classification)}]")
            lines.append(
                f"  Pass:     {_fmt_pass_summary(task.before)} -> {_fmt_pass_summary(task.after)}"
            )
            for delta in task.metrics[1:]:
                metric_label = _task_metric_display_label(delta.label)
                lines.append(
                    f"  {metric_label + ':':<9} {_fmt_metric_value(delta.label, delta.before)} -> "
                    f"{_fmt_metric_value(delta.label, delta.after)}"
                )
            if task.before.get("samples_with_metrics") != task.after.get("samples_with_metrics"):
                lines.append(
                    "  Metrics:  "
                    f"samples_with_metrics {task.before.get('samples_with_metrics')} -> "
                    f"{task.after.get('samples_with_metrics')}"
                )
            lines.append("")
        if lines[-1] == "":
            lines.pop()

    lines.append("")
    lines.append("Missing/new tasks")
    lines.append("-----------------")
    if not visible_context.missing_tasks and not visible_context.new_tasks:
        lines.append("(none)")
    else:
        for name in visible_context.missing_tasks:
            lines.append(f"{name}: present only in BEFORE")
        for name in visible_context.new_tasks:
            lines.append(f"{name}: present only in AFTER")

    return "\n".join(lines) + "\n"


def render_compare_markdown(
    comparison: Dict[str, Any],
    *,
    before_path: str,
    after_path: str,
    only_regressions: bool = False,
    only_improvements: bool = False,
    task_name: Optional[str] = None,
    show_unchanged: bool = False,
    sort_by: MetricName = "pass",
    thresholds: CompareThresholds = CompareThresholds(),
) -> str:
    """Render a markdown compare report suitable for PRs.

    Args:
        comparison: Output from :func:`compare_runs`.
        before_path: Baseline run path for the report header.
        after_path: Candidate run path for the report header.
        only_regressions: Include only regression tasks.
        only_improvements: Include only improvement tasks.
        task_name: Optional exact task-name filter.
        show_unchanged: Include unchanged tasks.
        sort_by: Metric family used for task sorting.
        thresholds: Active comparison thresholds.

    Returns:
        Formatted markdown compare report.
    """
    lines: List[str] = []
    lines.append("# monitor_bench compare")
    lines.append("")
    lines.append(f"- **Before:** `{before_path}`")
    lines.append(f"- **After:** `{after_path}`")
    lines.append("")

    if not _thresholds_are_default(thresholds):
        _append_threshold_markdown_lines(lines, thresholds)
        lines.append("")

    before_overall = comparison["before_summary"]["overall"]
    after_overall = comparison["after_summary"]["overall"]
    lines.append("## Overall summary")
    lines.append("")
    lines.append(
        f"- **Pass rate:** {_fmt_pass_summary(before_overall)} → {_fmt_pass_summary(after_overall)} "
        f"**[{_label_text(comparison['overall_classification'])}]**"
    )
    for delta in comparison["overall_metrics"][1:]:
        label = _overall_metric_display_label(delta.label)
        lines.append(
            f"- **{label}:** {_fmt_metric_value(delta.label, delta.before)} → "
            f"{_fmt_metric_value(delta.label, delta.after)} "
            f"**[{_label_text(_classify_metric(delta, thresholds) or 'unchanged')}]**"
        )

    visible_context = _build_visible_compare_context(
        comparison,
        only_regressions=only_regressions,
        only_improvements=only_improvements,
        show_unchanged=show_unchanged,
        task_name=task_name,
        sort_by=sort_by,
    )

    for classification, title in (
        ("regression", "Regressions"),
        ("improvement", "Improvements"),
        ("mixed", "Mixed changes"),
        ("unchanged", "Unchanged"),
    ):
        if classification == "unchanged" and not show_unchanged:
            continue
        items = visible_context.grouped_tasks[classification]
        lines.append("")
        lines.append(f"## {title}")
        lines.append("")
        if not items:
            lines.append("(none)")
            continue
        for task in items:
            lines.append(f"### `{task.task}` [{_label_text(task.classification)}]")
            lines.append("")
            lines.append(
                f"- **Pass:** {_fmt_pass_summary(task.before)} → {_fmt_pass_summary(task.after)}"
            )
            for delta in task.metrics[1:]:
                metric_label = _task_metric_display_label(delta.label)
                lines.append(
                    f"- **{metric_label}:** {_fmt_metric_value(delta.label, delta.before)} → "
                    f"{_fmt_metric_value(delta.label, delta.after)}"
                )
            if task.before.get("samples_with_metrics") != task.after.get("samples_with_metrics"):
                lines.append(
                    "- **Metrics:** "
                    f"`samples_with_metrics` {task.before.get('samples_with_metrics')} → "
                    f"{task.after.get('samples_with_metrics')}"
                )

    lines.append("")
    lines.append("## Missing/new tasks")
    lines.append("")
    if not visible_context.missing_tasks and not visible_context.new_tasks:
        lines.append("(none)")
    else:
        for name in visible_context.missing_tasks:
            lines.append(f"- `{name}`: present only in **BEFORE**")
        for name in visible_context.new_tasks:
            lines.append(f"- `{name}`: present only in **AFTER**")

    return "\n".join(lines) + "\n"


def render_compare_json(
    comparison: Dict[str, Any],
    *,
    before_path: str,
    after_path: str,
    only_regressions: bool = False,
    only_improvements: bool = False,
    task_name: Optional[str] = None,
    show_unchanged: bool = False,
    sort_by: MetricName = "pass",
    thresholds: CompareThresholds = CompareThresholds(),
) -> str:
    """Render a machine-readable JSON compare report.

    Args:
        comparison: Output from :func:`compare_runs`.
        before_path: Baseline run path for the report payload.
        after_path: Candidate run path for the report payload.
        only_regressions: Include only regression tasks.
        only_improvements: Include only improvement tasks.
        task_name: Optional exact task-name filter.
        show_unchanged: Include unchanged tasks.
        sort_by: Metric family used for task sorting.
        thresholds: Active comparison thresholds.

    Returns:
        JSON string containing the structured compare payload.
    """
    visible_context = _build_visible_compare_context(
        comparison,
        only_regressions=only_regressions,
        only_improvements=only_improvements,
        show_unchanged=show_unchanged,
        task_name=task_name,
        sort_by=sort_by,
    )

    payload = {
        "before_path": before_path,
        "after_path": after_path,
        "thresholds": _serialize_thresholds(thresholds),
        "overall_classification": comparison["overall_classification"],
        "overall_metrics": [
            _serialize_metric_delta(delta, thresholds) for delta in comparison["overall_metrics"]
        ],
        "tasks": [_serialize_task_comparison(task, thresholds) for task in visible_context.tasks],
        "missing_tasks": visible_context.missing_tasks,
        "new_tasks": visible_context.new_tasks,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for benchmark run comparison."""
    parser = argparse.ArgumentParser(
        description="Compare two monitor_bench run JSON files."
    )
    parser.add_argument("before_json", type=Path, help="Path to the baseline run JSON.")
    parser.add_argument("after_json", type=Path, help="Path to the candidate run JSON.")
    parser.add_argument(
        "--only-regressions",
        action="store_true",
        help="Show only tasks classified as regressions.",
    )
    parser.add_argument(
        "--only-improvements",
        action="store_true",
        help="Show only tasks classified as improvements.",
    )
    parser.add_argument(
        "--task",
        type=str,
        default=None,
        help="Filter to one exact task name.",
    )
    parser.add_argument(
        "--show-unchanged",
        action="store_true",
        help="Include unchanged tasks in the task sections.",
    )
    parser.add_argument(
        "--sort-by",
        choices=["pass", "cost", "tools", "loops", "duration"],
        default="pass",
        help="Sort task sections by the size of the chosen delta.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "markdown", "json"],
        default="text",
        help="Output format for the compare report.",
    )
    parser.add_argument(
        "--pass-rate-delta-threshold",
        type=float,
        default=CompareThresholds.pass_rate,
        help="Minimum absolute pass-rate delta required to classify a pass-rate change.",
    )
    parser.add_argument(
        "--cost-delta-threshold",
        type=float,
        default=CompareThresholds.cost,
        help="Minimum absolute cost delta required to classify a cost change.",
    )
    parser.add_argument(
        "--tool-delta-threshold",
        type=float,
        default=CompareThresholds.tools,
        help="Minimum absolute tool-call delta required to classify a tool-call change.",
    )
    parser.add_argument(
        "--loop-delta-threshold",
        type=float,
        default=CompareThresholds.loops,
        help="Minimum absolute loop-trip delta required to classify a loop-trip change.",
    )
    parser.add_argument(
        "--duration-delta-threshold",
        type=float,
        default=CompareThresholds.duration,
        help="Minimum absolute duration delta required to classify a duration change.",
    )
    args = parser.parse_args(argv)

    if args.only_regressions and args.only_improvements:
        parser.error("--only-regressions and --only-improvements cannot be used together")

    thresholds = CompareThresholds(
        pass_rate=args.pass_rate_delta_threshold,
        cost=args.cost_delta_threshold,
        tools=args.tool_delta_threshold,
        loops=args.loop_delta_threshold,
        duration=args.duration_delta_threshold,
    )

    before_run = json.loads(args.before_json.read_text())
    after_run = json.loads(args.after_json.read_text())
    comparison = compare_runs(before_run, after_run, thresholds=thresholds)

    if args.format == "text":
        output = render_compare_report(
            comparison,
            before_path=str(args.before_json),
            after_path=str(args.after_json),
            only_regressions=args.only_regressions,
            only_improvements=args.only_improvements,
            task_name=args.task,
            show_unchanged=args.show_unchanged,
            sort_by=args.sort_by,
            thresholds=thresholds,
        )
    elif args.format == "markdown":
        output = render_compare_markdown(
            comparison,
            before_path=str(args.before_json),
            after_path=str(args.after_json),
            only_regressions=args.only_regressions,
            only_improvements=args.only_improvements,
            task_name=args.task,
            show_unchanged=args.show_unchanged,
            sort_by=args.sort_by,
            thresholds=thresholds,
        )
    else:
        output = render_compare_json(
            comparison,
            before_path=str(args.before_json),
            after_path=str(args.after_json),
            only_regressions=args.only_regressions,
            only_improvements=args.only_improvements,
            task_name=args.task,
            show_unchanged=args.show_unchanged,
            sort_by=args.sort_by,
            thresholds=thresholds,
        )
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
