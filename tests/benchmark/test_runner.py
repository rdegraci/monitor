"""Unit tests for benchmark.monitor_bench.runner.

The runner shells out to ``python -m monitor --script ...`` — these tests
mock subprocess.run so they don't actually invoke monitor. The behavior
we care about: task discovery, script generation, metrics-JSON ingestion,
grader error handling, and the sample-loop arithmetic.

The real end-to-end smoke (subprocess actually launches) lives in
tasks/smoke_dump_metrics/ and is exercised by running the runner against
its own checked-in task — see README.md for how to invoke it manually.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from benchmark.monitor_bench import runner


# ---------------------------------------------------------------------------
# discover_tasks
# ---------------------------------------------------------------------------


def _write_task(tasks_dir: Path, name: str, body: str) -> None:
    d = tasks_dir / name
    d.mkdir(parents=True)
    (d / "task.py").write_text(body)


def test_discover_tasks_skips_dotfiles_and_underscores(tmp_path, monkeypatch):
    """Hidden dirs and underscore-prefixed dirs (templates, internals) must
    be excluded — otherwise a `tasks/_template/` would crash discovery."""
    monkeypatch.setattr(runner, "TASKS_DIR", tmp_path)
    _write_task(tmp_path, "good_one", 'NAME="g"\nTAGS=["x"]\nPROMPT="hi"\ndef grade(*a,**k): return True, ""')
    _write_task(tmp_path, "_template", "NAME='t'")
    (tmp_path / ".hidden").mkdir()

    found = runner.discover_tasks()
    names = [n for n, _ in found]
    assert names == ["good_one"]


def test_discover_tasks_filter_matches_name_or_tag(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "TASKS_DIR", tmp_path)
    _write_task(tmp_path, "memory_recall", 'NAME="m"\nTAGS=["memory"]\nPROMPT="x"\ndef grade(*a,**k): return True, ""')
    _write_task(tmp_path, "todo_plan", 'NAME="t"\nTAGS=["todo","planning"]\nPROMPT="x"\ndef grade(*a,**k): return True, ""')

    # Substring match on directory name.
    assert [n for n, _ in runner.discover_tasks(["recall"])] == ["memory_recall"]
    # Substring match on a tag.
    assert [n for n, _ in runner.discover_tasks(["planning"])] == ["todo_plan"]
    # Filter that matches both via shared tag.
    names = sorted(n for n, _ in runner.discover_tasks(["memory"]))
    # "memory" matches memory_recall directly and would only match todo_plan
    # if it shared the tag; it doesn't. Pin only memory_recall.
    assert names == ["memory_recall"]
    # OR with multiple filters: ["recall", "todo"] matches both.
    names = sorted(n for n, _ in runner.discover_tasks(["recall", "todo"]))
    assert names == ["memory_recall", "todo_plan"]


def test_discover_tasks_returns_empty_when_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "TASKS_DIR", tmp_path / "does_not_exist")
    assert runner.discover_tasks() == []


# ---------------------------------------------------------------------------
# _build_script
# ---------------------------------------------------------------------------


def test_build_script_appends_metrics_and_history_dumps(tmp_path):
    script = runner._build_script(
        "Do the thing.",
        tmp_path / "metrics.json",
        tmp_path / "history.json",
    )
    lines = script.splitlines()
    assert len(lines) == 3
    assert lines[0] == "Do the thing."
    assert lines[1] == f":dump_metrics {tmp_path / 'metrics.json'}"
    assert lines[2] == f":dump_history {tmp_path / 'history.json'}"


def test_build_script_history_comes_after_metrics(tmp_path):
    """Order matters: :dump_history is last so the dumped transcript
    includes the :dump_metrics built-in invocation (no-op for history
    content but useful for debugging that the metrics dump actually
    fired). Swapping the order would silently make analysis harder."""
    script = runner._build_script("prompt", tmp_path / "m.json", tmp_path / "h.json")
    metrics_pos = script.index(":dump_metrics")
    history_pos = script.index(":dump_history")
    assert metrics_pos < history_pos


def test_build_script_strips_trailing_whitespace_from_prompt(tmp_path):
    """A prompt with a trailing newline shouldn't produce a blank line
    between the prompt and :dump_metrics — run_script ignores empty
    lines but a blank in the middle is still ugly and surprising."""
    script = runner._build_script(
        "Hi there.\n\n",
        tmp_path / "m.json",
        tmp_path / "h.json",
    )
    assert script == (
        f"Hi there.\n"
        f":dump_metrics {tmp_path / 'm.json'}\n"
        f":dump_history {tmp_path / 'h.json'}\n"
    )


# ---------------------------------------------------------------------------
# run_one_sample (mocked subprocess)
# ---------------------------------------------------------------------------


def _stub_task_module(
    *,
    prompt="hello",
    tags=None,
    grade=None,
    setup=None,
):
    mod = types.ModuleType("stub_task")
    mod.NAME = "stub"
    mod.TAGS = list(tags or [])
    mod.PROMPT = prompt
    if grade is not None:
        mod.grade = grade
    if setup is not None:
        mod.setup = setup
    return mod


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_one_sample_writes_metrics_and_passes(monkeypatch):
    """The runner generates a script, the (mocked) subprocess writes a
    metrics JSON to the path the runner picked, the grader sees it and
    passes. Also writes a history envelope so history ingestion is
    exercised end-to-end."""
    captured = {}

    def fake_subprocess_run(cmd, *, cwd, env, capture_output, text, timeout, check):
        captured["cmd"] = cmd
        captured["cwd"] = Path(cwd)
        # Simulate monitor writing :dump_metrics and :dump_history.
        (Path(cwd) / runner.METRICS_FILENAME).write_text(
            json.dumps({"schema_version": 1, "session_cost_usd": 0.0})
        )
        (Path(cwd) / runner.HISTORY_FILENAME).write_text(
            json.dumps({
                "schema_version": 1,
                "conversation": [{"role": "user", "content": "hi"}],
            })
        )
        return _FakeProc(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    def grade(workspace, metrics, stdout, stderr, exit_code):
        return metrics["schema_version"] == 1, "ok"

    mod = _stub_task_module(grade=grade, tags=["t1"])
    result = runner.run_one_sample("stub_task", mod, sample_idx=0, model=None, timeout=10)

    assert result.passed is True
    assert result.exit_code == 0
    assert result.metrics == {"schema_version": 1, "session_cost_usd": 0.0}
    assert result.conversation_history == [{"role": "user", "content": "hi"}]
    assert result.tags == ["t1"]
    # Sanity-check the dispatched command shape.
    assert captured["cmd"][1:3] == ["-m", "monitor"]
    assert "--script" in captured["cmd"]


def test_run_one_sample_passes_history_to_grader_when_declared(monkeypatch):
    """A grader that declares a ``history`` parameter receives the
    parsed conversation list. Legacy graders without it still work
    (covered by test_run_one_sample_writes_metrics_and_passes above)."""
    seen = {}

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout, check):
        (Path(cwd) / runner.METRICS_FILENAME).write_text('{"schema_version": 1}')
        (Path(cwd) / runner.HISTORY_FILENAME).write_text(json.dumps({
            "schema_version": 1,
            "conversation": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
            ],
        }))
        return _FakeProc(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    def grade_with_history(workspace, metrics, stdout, stderr, exit_code, history=None):
        seen["history"] = history
        return history is not None and len(history) == 3, "saw history"

    mod = _stub_task_module(grade=grade_with_history)
    result = runner.run_one_sample("stub", mod, 0, model=None, timeout=10)
    assert result.passed is True
    assert seen["history"][1] == {"role": "user", "content": "u1"}


def test_run_one_sample_passes_history_under_alternate_name(monkeypatch):
    """The runner also honors graders that name the parameter
    ``conversation_history`` (more explicit, matching SampleResult)."""
    seen = {}

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout, check):
        (Path(cwd) / runner.METRICS_FILENAME).write_text("{}")
        (Path(cwd) / runner.HISTORY_FILENAME).write_text(json.dumps({
            "conversation": [{"role": "user", "content": "X"}],
        }))
        return _FakeProc(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    def grade(workspace, metrics, stdout, stderr, exit_code, conversation_history=None):
        seen["ch"] = conversation_history
        return True, "ok"

    mod = _stub_task_module(grade=grade)
    runner.run_one_sample("stub", mod, 0, model=None, timeout=10)
    assert seen["ch"] == [{"role": "user", "content": "X"}]


def test_run_one_sample_legacy_grader_signature_still_works(monkeypatch):
    """An existing 5-arg grader (no history param) must keep working —
    the runner inspects the signature and only passes history when the
    grader explicitly opts in. This is the backward-compat guarantee."""

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout, check):
        (Path(cwd) / runner.METRICS_FILENAME).write_text("{}")
        (Path(cwd) / runner.HISTORY_FILENAME).write_text('{"conversation": []}')
        return _FakeProc(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    # 5-positional, no history kwarg — pre-history-feature signature.
    def legacy_grade(workspace, metrics, stdout, stderr, exit_code):
        return True, "legacy ok"

    mod = _stub_task_module(grade=legacy_grade)
    result = runner.run_one_sample("stub", mod, 0, model=None, timeout=10)
    assert result.passed is True
    # History was still ingested into SampleResult even though the grader
    # didn't ask for it — the data is there for analysis even when this
    # particular task doesn't use it.
    assert result.conversation_history == []


def test_run_one_sample_handles_missing_history_file(monkeypatch):
    """If :dump_history never fires (e.g., subprocess crashed before
    reaching that line) the runner sets conversation_history=None and
    moves on without erroring."""

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout, check):
        (Path(cwd) / runner.METRICS_FILENAME).write_text('{"schema_version": 1}')
        # No history file written.
        return _FakeProc(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    mod = _stub_task_module(grade=lambda *a, **k: (True, "ok"))
    result = runner.run_one_sample("stub", mod, 0, model=None, timeout=10)
    assert result.metrics is not None
    assert result.conversation_history is None


def test_run_one_sample_handles_corrupt_history_file(monkeypatch):
    """A malformed history JSON must surface in stderr_tail but not
    crash the run — the metrics path is independent and may still
    succeed."""

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout, check):
        (Path(cwd) / runner.METRICS_FILENAME).write_text('{"schema_version": 1}')
        (Path(cwd) / runner.HISTORY_FILENAME).write_text("not valid json {{{")
        return _FakeProc(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    mod = _stub_task_module(grade=lambda *a, **k: (True, "metrics-only grade"))
    result = runner.run_one_sample("stub", mod, 0, model=None, timeout=10)
    assert result.metrics is not None
    assert result.conversation_history is None
    assert "history JSON parse failed" in result.stderr_tail


def test_run_one_sample_passes_model_when_given(monkeypatch):
    captured = {}

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout, check):
        captured["cmd"] = cmd
        return _FakeProc(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    mod = _stub_task_module(grade=lambda *a, **k: (False, "ignored"))
    runner.run_one_sample("stub", mod, 0, model="gpt-5.4-mini", timeout=10)
    assert "--model" in captured["cmd"]
    assert "gpt-5.4-mini" in captured["cmd"]


def test_run_one_sample_marks_timeout(monkeypatch):
    """A subprocess.TimeoutExpired must surface as timed_out=True so the
    grader can distinguish that from a clean exit. The runner still
    invokes the grader — it's the grader's call whether timeout = fail,
    not the runner's."""
    seen = {}

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout, check):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout, output=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    def grade(workspace, metrics, stdout, stderr, exit_code):
        # Mirrors how a real grader would behave: see no metrics + the
        # TIMEOUT marker in stderr, fail the run.
        seen["stderr"] = stderr
        passed = "TIMEOUT" not in stderr
        return passed, "timeout-aware grader"

    mod = _stub_task_module(grade=grade)
    result = runner.run_one_sample("stub", mod, 0, model=None, timeout=1)
    assert result.timed_out is True
    assert result.passed is False
    assert "TIMEOUT" in seen["stderr"]


def test_run_one_sample_handles_missing_metrics(monkeypatch):
    """When :dump_metrics doesn't fire (script crashed, model errored,
    etc.) the runner must hand the grader metrics=None — the grader
    decides what to do with that."""

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout, check):
        # Don't write any metrics file.
        return _FakeProc(returncode=1, stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    seen = {}

    def grade(workspace, metrics, stdout, stderr, exit_code):
        seen["metrics"] = metrics
        seen["exit_code"] = exit_code
        return False, f"expected metrics, got {metrics!r}"

    mod = _stub_task_module(grade=grade)
    result = runner.run_one_sample("stub", mod, 0, model=None, timeout=10)
    assert seen["metrics"] is None
    assert seen["exit_code"] == 1
    assert result.passed is False
    assert "boom" in result.stderr_tail


def test_run_one_sample_catches_grader_exception(monkeypatch):
    """If a task's grade() raises, the runner reports it as a failure
    with a traceback — never propagates up and kills the whole run."""

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout, check):
        (Path(cwd) / runner.METRICS_FILENAME).write_text("{}")
        return _FakeProc(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    def boom_grade(*args, **kwargs):
        raise RuntimeError("grader is buggy")

    mod = _stub_task_module(grade=boom_grade)
    result = runner.run_one_sample("stub", mod, 0, model=None, timeout=10)
    assert result.passed is False
    assert "grader is buggy" in result.detail
    assert result.error is not None
    assert "RuntimeError" in result.error


def test_run_one_sample_runs_setup_in_workspace(monkeypatch):
    """A task's setup() callback must receive the per-task tempdir so it
    can seed fixture files before monitor launches."""
    setup_args = {}

    def my_setup(workspace):
        setup_args["workspace"] = Path(workspace)
        (Path(workspace) / "fixture.txt").write_text("seeded")

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout, check):
        # Confirm setup ran against the same cwd as the subprocess.
        assert (Path(cwd) / "fixture.txt").read_text() == "seeded"
        (Path(cwd) / runner.METRICS_FILENAME).write_text('{"schema_version": 1}')
        return _FakeProc(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    mod = _stub_task_module(setup=my_setup, grade=lambda *a, **k: (True, "fixture present"))
    result = runner.run_one_sample("stub", mod, 0, model=None, timeout=10)
    assert result.passed is True
    assert setup_args["workspace"].name.startswith("mb-stub-s0-")


def test_run_one_sample_handles_setup_exception(monkeypatch):
    def boom_setup(workspace):
        raise OSError("fixture missing")

    # No subprocess should run if setup fails — guard against accidentally
    # launching monitor on an unseeded workspace.
    def fake_run(*a, **kw):
        raise AssertionError("subprocess should not have launched")

    monkeypatch.setattr(subprocess, "run", fake_run)

    mod = _stub_task_module(setup=boom_setup, grade=lambda *a, **k: (True, "ignored"))
    result = runner.run_one_sample("stub", mod, 0, model=None, timeout=10)
    assert result.passed is False
    assert "fixture missing" in result.detail


# ---------------------------------------------------------------------------
# run() — sample-loop arithmetic
# ---------------------------------------------------------------------------


def test_run_produces_N_samples_per_task(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "TASKS_DIR", tmp_path)
    _write_task(
        tmp_path,
        "alpha",
        'NAME="a"\nTAGS=["x"]\nPROMPT="p"\ndef grade(*a,**k): return True, "ok"\n',
    )
    _write_task(
        tmp_path,
        "beta",
        'NAME="b"\nTAGS=["x"]\nPROMPT="p"\ndef grade(*a,**k): return True, "ok"\n',
    )

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout, check):
        (Path(cwd) / runner.METRICS_FILENAME).write_text('{"schema_version": 1}')
        return _FakeProc(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    report = runner.run(samples=3)
    assert len(report.results) == 6  # 2 tasks * 3 samples
    samples_by_task = {}
    for r in report.results:
        samples_by_task.setdefault(r.task, set()).add(r.sample)
    assert samples_by_task == {"alpha": {0, 1, 2}, "beta": {0, 1, 2}}
