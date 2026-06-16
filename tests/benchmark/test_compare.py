"""Unit tests for benchmark.monitor_bench.compare.

The compare helper sits between raw run JSON and a developer's decision about
whether a change improved or regressed benchmark behavior. These tests pin the
classification, filtering, and rendering rules for the phase 1 and 2 feature
set.
"""

from __future__ import annotations

import json

import pytest

from benchmark.monitor_bench import compare


def _result(
    task,
    sample,
    passed,
    *,
    tags=None,
    cost=None,
    tool_calls=None,
    loop_trips=None,
    duration=1.0,
):
    """Build a dict matching runner.SampleResult JSON for compare tests."""
    metrics = None
    if any(value is not None for value in (cost, tool_calls, loop_trips)):
        metrics = {
            "session_cost_usd": cost or 0.0,
            "session_tool_call_count": tool_calls or 0,
            "session_loop_detector_trips": loop_trips or 0,
            "session_total_tokens": 0,
        }
    return {
        "task": task,
        "sample": sample,
        "passed": passed,
        "tags": list(tags or []),
        "metrics": metrics,
        "duration_seconds": duration,
    }


def _run(*results):
    """Wrap result rows in the minimal run JSON envelope."""
    return {
        "samples_per_task": 2,
        "results": list(results),
    }


def test_compare_runs_classifies_pass_rate_improvement():
    before = _run(
        _result("alpha", 0, True, cost=0.10, tool_calls=4),
        _result("alpha", 1, False, cost=0.20, tool_calls=6),
    )
    after = _run(
        _result("alpha", 0, True, cost=0.30, tool_calls=7),
        _result("alpha", 1, True, cost=0.40, tool_calls=9),
    )

    comparison = compare.compare_runs(before, after)

    assert comparison["overall_classification"] == "mixed"
    assert comparison["tasks"][0].classification == "mixed"


def test_compare_runs_classifies_efficiency_regression_when_pass_rate_unchanged():
    before = _run(
        _result("alpha", 0, True, cost=0.10, tool_calls=4, loop_trips=0, duration=2.0),
        _result("alpha", 1, True, cost=0.20, tool_calls=5, loop_trips=0, duration=2.0),
    )
    after = _run(
        _result("alpha", 0, True, cost=0.60, tool_calls=10, loop_trips=1, duration=6.0),
        _result("alpha", 1, True, cost=0.70, tool_calls=11, loop_trips=1, duration=6.0),
    )

    comparison = compare.compare_runs(before, after)

    assert comparison["overall_classification"] == "regression"
    assert comparison["tasks"][0].classification == "regression"


def test_compare_runs_classifies_mixed_when_metrics_split():
    before = _run(
        _result("alpha", 0, True, cost=0.60, tool_calls=10, loop_trips=0, duration=6.0),
        _result("alpha", 1, True, cost=0.70, tool_calls=11, loop_trips=0, duration=6.0),
    )
    after = _run(
        _result("alpha", 0, True, cost=0.10, tool_calls=12, loop_trips=0, duration=7.0),
        _result("alpha", 1, True, cost=0.20, tool_calls=13, loop_trips=0, duration=7.0),
    )

    comparison = compare.compare_runs(before, after)

    assert comparison["overall_classification"] == "mixed"
    assert comparison["tasks"][0].classification == "mixed"


def test_compare_runs_detects_missing_and_new_tasks():
    before = _run(
        _result("before_only", 0, True, cost=0.10, tool_calls=1),
        _result("shared", 0, True, cost=0.20, tool_calls=2),
    )
    after = _run(
        _result("shared", 0, True, cost=0.10, tool_calls=1),
        _result("after_only", 0, True, cost=0.30, tool_calls=3),
    )

    comparison = compare.compare_runs(before, after)

    assert comparison["missing_tasks"] == ["before_only"]
    assert comparison["new_tasks"] == ["after_only"]


def test_compare_runs_preserves_missing_metrics_semantics():
    before = _run(
        _result("alpha", 0, True, cost=0.40, tool_calls=4),
        _result("alpha", 1, False, cost=None),
    )
    after = _run(
        _result("alpha", 0, True, cost=0.20, tool_calls=2),
        _result("alpha", 1, False, cost=None),
    )

    comparison = compare.compare_runs(before, after)
    task = comparison["tasks"][0]

    assert task.before["avg_cost_usd"] == pytest.approx(0.40)
    assert task.after["avg_cost_usd"] == pytest.approx(0.20)
    assert task.before["samples_with_metrics"] == 1
    assert task.after["samples_with_metrics"] == 1


def test_render_compare_report_omits_unchanged_by_default():
    before = _run(
        _result("changed", 0, True, cost=0.50, tool_calls=5),
        _result("same", 0, True, cost=0.20, tool_calls=2),
    )
    after = _run(
        _result("changed", 0, True, cost=0.10, tool_calls=1),
        _result("same", 0, True, cost=0.20, tool_calls=2),
    )

    text = compare.render_compare_report(
        compare.compare_runs(before, after),
        before_path="before.json",
        after_path="after.json",
    )

    assert "changed [IMPROVEMENT]" in text
    assert "same [UNCHANGED]" not in text


def test_render_compare_report_show_unchanged_includes_unchanged_section():
    before = _run(_result("same", 0, True, cost=0.20, tool_calls=2))
    after = _run(_result("same", 0, True, cost=0.20, tool_calls=2))

    text = compare.render_compare_report(
        compare.compare_runs(before, after),
        before_path="before.json",
        after_path="after.json",
        show_unchanged=True,
    )

    assert "Unchanged" in text
    assert "same [UNCHANGED]" in text


def test_render_compare_report_only_regressions_filters_other_categories():
    before = _run(
        _result("better", 0, True, cost=0.50, tool_calls=5),
        _result("worse", 0, True, cost=0.10, tool_calls=1),
    )
    after = _run(
        _result("better", 0, True, cost=0.10, tool_calls=1),
        _result("worse", 0, True, cost=0.50, tool_calls=5),
    )

    text = compare.render_compare_report(
        compare.compare_runs(before, after),
        before_path="before.json",
        after_path="after.json",
        only_regressions=True,
    )

    assert "worse [REGRESSION]" in text
    assert "better [IMPROVEMENT]" not in text


def test_render_compare_report_only_improvements_filters_other_categories():
    before = _run(
        _result("better", 0, True, cost=0.50, tool_calls=5),
        _result("worse", 0, True, cost=0.10, tool_calls=1),
    )
    after = _run(
        _result("better", 0, True, cost=0.10, tool_calls=1),
        _result("worse", 0, True, cost=0.50, tool_calls=5),
    )

    text = compare.render_compare_report(
        compare.compare_runs(before, after),
        before_path="before.json",
        after_path="after.json",
        only_improvements=True,
    )

    assert "better [IMPROVEMENT]" in text
    assert "worse [REGRESSION]" not in text


def test_render_compare_report_task_filter_limits_output_and_missing_new():
    before = _run(
        _result("alpha", 0, True, cost=0.20, tool_calls=2),
        _result("before_only", 0, True, cost=0.10, tool_calls=1),
    )
    after = _run(
        _result("alpha", 0, True, cost=0.50, tool_calls=5),
        _result("after_only", 0, True, cost=0.30, tool_calls=3),
    )

    text = compare.render_compare_report(
        compare.compare_runs(before, after),
        before_path="before.json",
        after_path="after.json",
        task_name="alpha",
    )

    assert "alpha [REGRESSION]" in text
    assert "before_only" not in text
    assert "after_only" not in text


def test_render_compare_report_sort_by_orders_largest_delta_first():
    before = _run(
        _result("small", 0, True, cost=0.50, tool_calls=5),
        _result("large", 0, True, cost=1.00, tool_calls=5),
    )
    after = _run(
        _result("small", 0, True, cost=0.40, tool_calls=5),
        _result("large", 0, True, cost=0.10, tool_calls=5),
    )

    text = compare.render_compare_report(
        compare.compare_runs(before, after),
        before_path="before.json",
        after_path="after.json",
        sort_by="cost",
    )

    assert text.index("large [IMPROVEMENT]") < text.index("small [IMPROVEMENT]")


def test_render_compare_markdown_contains_expected_sections():
    before = _run(
        _result("alpha", 0, True, cost=0.50, tool_calls=5),
        _result("beta", 0, True, cost=0.10, tool_calls=1),
    )
    after = _run(
        _result("alpha", 0, True, cost=0.10, tool_calls=1),
        _result("beta", 0, True, cost=0.50, tool_calls=5),
    )

    markdown = compare.render_compare_markdown(
        compare.compare_runs(before, after),
        before_path="before.json",
        after_path="after.json",
    )

    assert "# monitor_bench compare" in markdown
    assert "## Overall summary" in markdown
    assert "## Regressions" in markdown
    assert "## Improvements" in markdown
    assert "### `alpha` [IMPROVEMENT]" in markdown
    assert "### `beta` [REGRESSION]" in markdown


def test_render_compare_json_returns_structured_payload():
    before = _run(
        _result("alpha", 0, True, cost=0.50, tool_calls=5),
        _result("before_only", 0, True, cost=0.10, tool_calls=1),
    )
    after = _run(
        _result("alpha", 0, True, cost=0.10, tool_calls=1),
        _result("after_only", 0, True, cost=0.20, tool_calls=2),
    )

    payload = compare.render_compare_json(
        compare.compare_runs(before, after),
        before_path="before.json",
        after_path="after.json",
    )

    parsed = json.loads(payload)
    assert parsed["before_path"] == "before.json"
    assert parsed["after_path"] == "after.json"
    assert parsed["overall_classification"] == "improvement"
    assert parsed["missing_tasks"] == ["before_only"]
    assert parsed["new_tasks"] == ["after_only"]
    assert parsed["tasks"][0]["task"] == "alpha"
    assert parsed["tasks"][0]["classification"] == "improvement"
    assert parsed["overall_metrics"][0]["label"] == "pass"


def test_render_compare_json_respects_filters():
    before = _run(
        _result("better", 0, True, cost=0.50, tool_calls=5),
        _result("worse", 0, True, cost=0.10, tool_calls=1),
    )
    after = _run(
        _result("better", 0, True, cost=0.10, tool_calls=1),
        _result("worse", 0, True, cost=0.50, tool_calls=5),
    )

    payload = compare.render_compare_json(
        compare.compare_runs(before, after),
        before_path="before.json",
        after_path="after.json",
        only_regressions=True,
    )

    parsed = json.loads(payload)
    assert [task["task"] for task in parsed["tasks"]] == ["worse"]


def test_compare_runs_thresholds_can_suppress_small_efficiency_changes():
    before = _run(
        _result("alpha", 0, True, cost=0.100, tool_calls=5, duration=5.0),
        _result("alpha", 1, True, cost=0.100, tool_calls=5, duration=5.0),
    )
    after = _run(
        _result("alpha", 0, True, cost=0.105, tool_calls=5, duration=5.2),
        _result("alpha", 1, True, cost=0.105, tool_calls=5, duration=5.2),
    )

    thresholds = compare.CompareThresholds(cost=0.01, duration=0.5)
    comparison = compare.compare_runs(before, after, thresholds=thresholds)

    assert comparison["overall_classification"] == "unchanged"
    assert comparison["tasks"][0].classification == "unchanged"


def test_compare_runs_pass_rate_improvement_becomes_mixed_with_thresholded_regressions():
    before = _run(
        _result("alpha", 0, True, cost=0.10, tool_calls=2),
        _result("alpha", 1, False, cost=0.10, tool_calls=2),
    )
    after = _run(
        _result("alpha", 0, True, cost=0.50, tool_calls=8),
        _result("alpha", 1, True, cost=0.50, tool_calls=8),
    )

    thresholds = compare.CompareThresholds(cost=0.1, tools=1.0)
    comparison = compare.compare_runs(before, after, thresholds=thresholds)

    assert comparison["overall_classification"] == "mixed"
    assert comparison["tasks"][0].classification == "mixed"


def test_compare_runs_pass_rate_regression_still_dominates_when_efficiency_improves():
    before = _run(
        _result("alpha", 0, True, cost=0.60, tool_calls=8),
        _result("alpha", 1, True, cost=0.60, tool_calls=8),
    )
    after = _run(
        _result("alpha", 0, True, cost=0.10, tool_calls=2),
        _result("alpha", 1, False, cost=0.10, tool_calls=2),
    )

    thresholds = compare.CompareThresholds(cost=0.1, tools=1.0)
    comparison = compare.compare_runs(before, after, thresholds=thresholds)

    assert comparison["overall_classification"] == "regression"
    assert comparison["tasks"][0].classification == "regression"


def test_render_compare_json_includes_threshold_metadata_and_metric_thresholds():
    before = _run(_result("alpha", 0, True, cost=0.50, tool_calls=5, duration=4.0))
    after = _run(_result("alpha", 0, True, cost=0.45, tool_calls=5, duration=4.1))

    thresholds = compare.CompareThresholds(cost=0.1, duration=0.5)
    payload = compare.render_compare_json(
        compare.compare_runs(before, after, thresholds=thresholds),
        before_path="before.json",
        after_path="after.json",
        thresholds=thresholds,
    )

    parsed = json.loads(payload)
    assert parsed["thresholds"] == {
        "pass_rate": 1e-09,
        "cost": 0.1,
        "tools": 0.0,
        "loops": 0.0,
        "duration": 0.5,
    }
    assert parsed["overall_metrics"][1]["threshold"] == 0.1
    assert parsed["tasks"] == []


def test_render_compare_report_shows_active_thresholds_when_non_default():
    before = _run(_result("alpha", 0, True, cost=0.50, tool_calls=5))
    after = _run(_result("alpha", 0, True, cost=0.45, tool_calls=5))

    thresholds = compare.CompareThresholds(cost=0.1)
    text = compare.render_compare_report(
        compare.compare_runs(before, after, thresholds=thresholds),
        before_path="before.json",
        after_path="after.json",
        thresholds=thresholds,
        show_unchanged=True,
    )

    assert "Thresholds" in text
    assert "Cost:         0.1" in text


def test_render_compare_markdown_shows_active_thresholds_when_non_default():
    before = _run(_result("alpha", 0, True, cost=0.50, tool_calls=5))
    after = _run(_result("alpha", 0, True, cost=0.45, tool_calls=5))

    thresholds = compare.CompareThresholds(cost=0.1)
    markdown = compare.render_compare_markdown(
        compare.compare_runs(before, after, thresholds=thresholds),
        before_path="before.json",
        after_path="after.json",
        thresholds=thresholds,
        show_unchanged=True,
    )

    assert "## Active thresholds" in markdown
    assert "- **Cost:** `0.1`" in markdown
