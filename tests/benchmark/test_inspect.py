"""Unit tests for benchmark.monitor_bench.inspect.

This helper is intentionally lightweight: it reads a run JSON produced by the
runner and prints a per-sample debugging view. These tests pin the filtering and
content-selection behavior so developers can rely on it after a benchmark run.
"""

from __future__ import annotations

from benchmark.monitor_bench import inspect as inspect_run


def _result(task, sample, passed, *, history=None, stderr_tail="", error=None, metrics=None):
    return {
        "task": task,
        "sample": sample,
        "passed": passed,
        "detail": "ok" if passed else "failed for reasons",
        "exit_code": 0 if passed else 1,
        "timed_out": False,
        "duration_seconds": 1.5,
        "metrics": metrics,
        "conversation_history": history,
        "stderr_tail": stderr_tail,
        "error": error,
    }


def test_inspect_run_shows_overall_summary():
    run = {
        "model": "test-model",
        "samples_per_task": 2,
        "results": [
            _result("a", 0, True),
            _result("b", 0, False),
        ],
    }
    text = inspect_run.inspect_run(run)
    assert "# monitor_bench inspect" in text
    assert "model: test-model" in text
    assert "overall: 1/2 passed" in text


def test_inspect_run_failed_only_filters_passes():
    run = {
        "results": [
            _result("a", 0, True),
            _result("b", 0, False),
        ],
    }
    text = inspect_run.inspect_run(run, failed_only=True)
    assert "task: b" in text
    assert "task: a" not in text


def test_inspect_run_task_filter_selects_exact_task():
    run = {
        "results": [
            _result("alpha", 0, False),
            _result("beta", 0, False),
        ],
    }
    text = inspect_run.inspect_run(run, task="beta")
    assert "task: beta" in text
    assert "task: alpha" not in text


def test_inspect_run_includes_final_assistant_and_error_sections():
    run = {
        "results": [
            _result(
                "a",
                0,
                False,
                history=[
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "final answer here"},
                ],
                stderr_tail="stderr text",
                error="traceback text",
                metrics={
                    "session_cost_usd": 0.12,
                    "session_tool_call_count": 4,
                    "session_loop_detector_trips": 0,
                    "session_total_tokens": 321,
                },
            )
        ]
    }
    text = inspect_run.inspect_run(run)
    assert "final_assistant:" in text
    assert "final answer here" in text
    assert "stderr_tail:" in text
    assert "stderr text" in text
    assert "error:" in text
    assert "traceback text" in text
    assert "tool_calls=4" in text


def test_inspect_run_show_history_includes_serialized_history():
    run = {
        "results": [
            _result(
                "a",
                0,
                False,
                history=[
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "world"},
                ],
            )
        ]
    }
    text = inspect_run.inspect_run(run, show_history=True)
    assert "conversation_history:" in text
    assert '"role": "assistant"' in text


def test_inspect_run_no_matching_samples_message():
    run = {"results": [_result("a", 0, True)]}
    text = inspect_run.inspect_run(run, failed_only=True)
    assert "No matching samples." in text
