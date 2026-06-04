"""Unit tests for benchmark.monitor_bench.report.

The aggregator turns a raw run JSON (one entry per sample) into per-task,
per-tag, and overall summaries. Tests pin the math (means, pass rates)
and the "missing metrics" edge case where a sample crashed before
:dump_metrics fired — those samples must count toward pass rate but
NOT toward cost/tool averages, otherwise crashed runs masquerade as $0.
"""

from __future__ import annotations

import pytest

from benchmark.monitor_bench import report


def _result(task, sample, passed, *, tags=None, cost=None, tool_calls=None, loop_trips=None, tokens=None, duration=1.0):
    """Build a dict matching what runner.SampleResult serializes to."""
    metrics = None
    if cost is not None or tool_calls is not None:
        metrics = {
            "session_cost_usd": cost or 0.0,
            "session_tool_call_count": tool_calls or 0,
            "session_loop_detector_trips": loop_trips or 0,
            "session_total_tokens": tokens or 0,
        }
    return {
        "task": task,
        "sample": sample,
        "passed": passed,
        "tags": list(tags or []),
        "metrics": metrics,
        "duration_seconds": duration,
    }


def test_aggregate_basic_pass_rate():
    run = {
        "samples_per_task": 3,
        "results": [
            _result("a", 0, True, cost=0.10, tool_calls=10),
            _result("a", 1, True, cost=0.20, tool_calls=20),
            _result("a", 2, False, cost=0.30, tool_calls=30),
        ],
    }
    summary = report.aggregate(run)
    a = summary["per_task"]["a"]
    assert a["n"] == 3
    assert a["passes"] == 2
    assert a["pass_rate"] == pytest.approx(2 / 3)
    assert a["avg_cost_usd"] == pytest.approx(0.20)
    assert a["avg_tool_calls"] == pytest.approx(20.0)


def test_aggregate_excludes_crashed_samples_from_cost_averages():
    """A sample with metrics=None (crashed before :dump_metrics) must
    count toward pass rate (it failed) but NOT toward avg_cost — otherwise
    a crashed run looks free, which makes regressions look like wins."""
    run = {
        "samples_per_task": 3,
        "results": [
            _result("a", 0, True, cost=0.50, tool_calls=10),
            _result("a", 1, False, cost=None),  # crashed — no metrics
            _result("a", 2, True, cost=0.30, tool_calls=20),
        ],
    }
    summary = report.aggregate(run)
    a = summary["per_task"]["a"]
    assert a["n"] == 3
    assert a["passes"] == 2
    # Mean of [0.50, 0.30] — the None sample is excluded.
    assert a["avg_cost_usd"] == pytest.approx(0.40)
    assert a["samples_with_metrics"] == 2


def test_aggregate_per_tag_rolls_up_across_tasks():
    """Each result contributes to every one of its tags. Two tasks
    sharing a tag should aggregate together under that tag."""
    run = {
        "results": [
            _result("a", 0, True, tags=["memory", "easy"], cost=0.10),
            _result("a", 1, True, tags=["memory", "easy"], cost=0.20),
            _result("b", 0, False, tags=["memory", "hard"], cost=1.00),
        ],
    }
    summary = report.aggregate(run)
    mem = summary["per_tag"]["memory"]
    assert mem["n"] == 3
    assert mem["passes"] == 2
    assert mem["avg_cost_usd"] == pytest.approx((0.10 + 0.20 + 1.00) / 3)
    # "easy" tag only has 2 samples; "hard" only has 1 — pinned to catch
    # accidental cross-tag bleeding.
    assert summary["per_tag"]["easy"]["n"] == 2
    assert summary["per_tag"]["hard"]["n"] == 1


def test_aggregate_empty_run_is_safe():
    summary = report.aggregate({"results": []})
    assert summary["overall"]["n"] == 0
    assert summary["overall"]["pass_rate"] == 0.0
    assert summary["overall"]["avg_cost_usd"] is None
    assert summary["per_task"] == {}
    assert summary["per_tag"] == {}


def test_render_markdown_contains_overall_and_per_task():
    summary = report.aggregate({
        "model": "test-model",
        "samples_per_task": 2,
        "results": [
            _result("alpha", 0, True, tags=["t1"], cost=0.10, tool_calls=5),
            _result("alpha", 1, True, tags=["t1"], cost=0.20, tool_calls=7),
        ],
    })
    md = report.render_markdown(summary)
    assert "test-model" in md
    assert "alpha" in md
    assert "2/2 (100%)" in md
    # Avg cost should appear in the per-task row.
    assert "$0.1500" in md


def test_render_markdown_handles_no_metrics_samples():
    """When every sample crashed before :dump_metrics, the per-task row
    must still render — using "—" rather than '$nan' or crashing."""
    summary = report.aggregate({
        "results": [_result("a", 0, False, cost=None), _result("a", 1, False, cost=None)],
    })
    md = report.render_markdown(summary)
    assert "0/2 (0%)" in md
    assert "—" in md  # placeholder for absent cost
