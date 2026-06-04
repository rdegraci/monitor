"""monitor_bench runner.

Launches Monitor as a subprocess (one process per (task, sample) pair),
feeds it a generated --script file containing the task prompt followed by
:dump_metrics, then grades the resulting workspace + metrics JSON.

Each task is a Python module under tasks/<task_name>/task.py exporting:

    NAME: str                # human display name
    TAGS: list[str]          # e.g. ["smoke", "memory", "todo"]
    PROMPT: str              # the line fed to monitor's --script
    setup(workspace) -> None # optional: seed fixture state in the tempdir
    grade(workspace, metrics, stdout, stderr, exit_code) -> (bool, str)

The runner is deliberately uncoupled from Monitor's internals — it just
invokes ``python -m monitor --script <file>`` and reads the JSON the
:dump_metrics built-in writes. That isolation is the whole point: bench
runs survive Monitor refactors as long as the CLI contract holds.
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("monitor_bench.runner")

# Resolve repo paths once at import time. The runner assumes it lives at
# benchmark/monitor_bench/runner.py inside the repo; ../../ is the repo
# root. Tasks live alongside this file under tasks/.
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
TASKS_DIR = HERE / "tasks"
RESULTS_DIR = HERE / "results"

# Sentinels for the per-sample dump files the runner appends to every
# script. Both names are fixed so the grader doesn't have to guess.
METRICS_FILENAME = "_bench_metrics.json"
HISTORY_FILENAME = "_bench_history.json"
SCRIPT_FILENAME = "_bench_script.txt"


@dataclass
class SampleResult:
    """Single (task, sample_idx) outcome — the atomic unit of the bench.

    ``metrics`` is the parsed :dump_metrics JSON (aggregate counters).
    ``conversation_history`` is the parsed :dump_history JSON's
    ``conversation`` list — the full transcript of the run. Both are
    None when the dump didn't fire (subprocess crashed before reaching
    the dump line, or wrote unparseable output).
    """
    task: str
    tags: List[str]
    sample: int
    passed: bool
    detail: str
    exit_code: int
    timed_out: bool
    duration_seconds: float
    metrics: Optional[Dict[str, Any]] = None
    conversation_history: Optional[List[Dict[str, Any]]] = None
    stderr_tail: str = ""
    error: Optional[str] = None


@dataclass
class RunReport:
    """Aggregate over all sample results in a single bench invocation."""
    started_at: float
    finished_at: float
    samples_per_task: int
    model: Optional[str]
    task_filter: Optional[List[str]]
    results: List[SampleResult] = field(default_factory=list)


def _load_task_module(task_dir: Path):
    """Dynamically import tasks/<name>/task.py without polluting sys.modules
    permanently — each task gets a unique module name to avoid clashes when
    two tasks happen to share a class or function name."""
    task_py = task_dir / "task.py"
    if not task_py.is_file():
        return None
    mod_name = f"monitor_bench._task_{task_dir.name}"
    spec = importlib.util.spec_from_file_location(mod_name, task_py)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def discover_tasks(task_filter: Optional[List[str]] = None) -> List[Tuple[str, Any]]:
    """Return [(task_name, task_module), ...] sorted by name.

    ``task_filter`` is a list of substrings; a task is included if any
    substring is found in its directory name OR in its TAGS list.
    """
    if not TASKS_DIR.is_dir():
        return []
    found: List[Tuple[str, Any]] = []
    for entry in sorted(TASKS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_") or entry.name.startswith("."):
            continue
        mod = _load_task_module(entry)
        if mod is None:
            logger.warning("Skipping %s: no task.py or import failed", entry.name)
            continue
        if task_filter:
            tags = getattr(mod, "TAGS", []) or []
            haystack = [entry.name] + list(tags)
            if not any(needle in h for needle in task_filter for h in haystack):
                continue
        found.append((entry.name, mod))
    return found


def _build_script(prompt: str, metrics_path: Path, history_path: Path) -> str:
    """Compose the --script body. Three lines:
       1. the task prompt (sent through process_input — could be an LLM
          query, a built-in, or a sequence of either)
       2. :dump_metrics <path> — aggregate counters
       3. :dump_history <path> — full conversation transcript

    Lines 2 and 3 only fire AFTER line 1's tool-call chain fully
    completes, because --script is synchronous line-by-line. The history
    is dumped LAST so it reflects the final state — including the
    :dump_metrics message itself, which is fine; analyzers can filter
    out trailing bench commands by tail-stripping.
    """
    return (
        f"{prompt.rstrip()}\n"
        f":dump_metrics {metrics_path}\n"
        f":dump_history {history_path}\n"
    )


def run_one_sample(
    task_name: str,
    task_module,
    sample_idx: int,
    model: Optional[str],
    timeout: int,
    python_executable: str = sys.executable,
) -> SampleResult:
    """Run a single (task, sample) and grade the outcome.

    The tempdir is the subprocess's cwd — monitor operates against
    whatever files setup() seeded there. The metrics file is written to
    a known relative path inside that tempdir so the grader can find it.
    """
    started = time.time()
    tags = list(getattr(task_module, "TAGS", []) or [])
    prompt = getattr(task_module, "PROMPT", None)
    if not isinstance(prompt, str) or not prompt.strip():
        return SampleResult(
            task=task_name,
            tags=tags,
            sample=sample_idx,
            passed=False,
            detail="task module has no PROMPT string",
            exit_code=-1,
            timed_out=False,
            duration_seconds=0.0,
            error="missing PROMPT",
        )

    workspace = Path(tempfile.mkdtemp(prefix=f"mb-{task_name}-s{sample_idx}-"))
    try:
        # Let the task seed fixture files (source code, redis state, etc.)
        setup = getattr(task_module, "setup", None)
        if callable(setup):
            try:
                setup(workspace)
            except Exception as e:
                return SampleResult(
                    task=task_name,
                    tags=tags,
                    sample=sample_idx,
                    passed=False,
                    detail=f"setup raised: {e}",
                    exit_code=-1,
                    timed_out=False,
                    duration_seconds=time.time() - started,
                    error=traceback.format_exc(),
                )

        metrics_path = workspace / METRICS_FILENAME
        history_path = workspace / HISTORY_FILENAME
        script_path = workspace / SCRIPT_FILENAME
        script_path.write_text(_build_script(prompt, metrics_path, history_path))

        cmd: List[str] = [python_executable, "-m", "monitor", "--script", str(script_path)]
        if model:
            cmd += ["--model", model]

        # Inherit env so credentials / config paths are picked up from the
        # caller's shell. The subprocess writes to metrics_path inside the
        # tempdir, which gets cleaned up after grading.
        env = os.environ.copy()

        timed_out = False
        stdout = stderr = ""
        exit_code = -1
        try:
            proc = subprocess.run(
                cmd,
                cwd=workspace,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            exit_code = proc.returncode
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
        except subprocess.TimeoutExpired as e:
            timed_out = True
            stdout = (e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")) or ""
            stderr = (e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")) or ""
            stderr += f"\n[runner] TIMEOUT after {timeout}s"

        metrics: Optional[Dict[str, Any]] = None
        if metrics_path.exists():
            try:
                metrics = json.loads(metrics_path.read_text())
            except Exception as e:
                stderr += f"\n[runner] metrics JSON parse failed: {e}"

        history: Optional[List[Dict[str, Any]]] = None
        if history_path.exists():
            try:
                history_envelope = json.loads(history_path.read_text())
                history = history_envelope.get("conversation")
            except Exception as e:
                stderr += f"\n[runner] history JSON parse failed: {e}"

        grade = getattr(task_module, "grade", None)
        if not callable(grade):
            return SampleResult(
                task=task_name,
                tags=tags,
                sample=sample_idx,
                passed=False,
                detail="task module has no grade() function",
                exit_code=exit_code,
                timed_out=timed_out,
                duration_seconds=time.time() - started,
                metrics=metrics,
                conversation_history=history,
                stderr_tail=stderr[-2000:],
                error="missing grade()",
            )

        # Backward-compat: older task graders have signature
        # ``grade(workspace, metrics, stdout, stderr, exit_code)`` and
        # don't expect a 6th positional. Inspect the signature and only
        # pass ``history`` when the grader explicitly accepts it (named
        # ``history`` or ``conversation_history``, or accepts **kwargs).
        # New graders should just declare the parameter; legacy ones
        # keep working unchanged.
        try:
            sig = inspect.signature(grade)
            params = sig.parameters
            accepts_history = (
                "history" in params
                or "conversation_history" in params
                or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
            )
        except (TypeError, ValueError):
            accepts_history = False

        try:
            if accepts_history:
                # Prefer the explicit parameter name the grader declared.
                if "conversation_history" in params:
                    passed, detail = grade(
                        workspace, metrics, stdout, stderr, exit_code,
                        conversation_history=history,
                    )
                else:
                    passed, detail = grade(
                        workspace, metrics, stdout, stderr, exit_code,
                        history=history,
                    )
            else:
                passed, detail = grade(workspace, metrics, stdout, stderr, exit_code)
        except Exception as e:
            return SampleResult(
                task=task_name,
                tags=tags,
                sample=sample_idx,
                passed=False,
                detail=f"grade() raised: {e}",
                exit_code=exit_code,
                timed_out=timed_out,
                duration_seconds=time.time() - started,
                metrics=metrics,
                conversation_history=history,
                stderr_tail=stderr[-2000:],
                error=traceback.format_exc(),
            )

        return SampleResult(
            task=task_name,
            tags=tags,
            sample=sample_idx,
            passed=bool(passed),
            detail=str(detail),
            exit_code=exit_code,
            timed_out=timed_out,
            duration_seconds=time.time() - started,
            metrics=metrics,
            conversation_history=history,
            stderr_tail=stderr[-2000:],
        )
    finally:
        # Tempdir cleanup — preserves nothing across runs. If users want
        # to inspect a failing run, they can re-run with KEEP_WORKSPACE=1.
        if not os.environ.get("MONITOR_BENCH_KEEP_WORKSPACE"):
            shutil.rmtree(workspace, ignore_errors=True)


def run(
    task_filter: Optional[List[str]] = None,
    samples: int = 3,
    timeout: int = 600,
    model: Optional[str] = None,
) -> RunReport:
    """Run the full bench: every discovered task × every sample."""
    started = time.time()
    tasks = discover_tasks(task_filter)
    results: List[SampleResult] = []
    for name, mod in tasks:
        print(f"[bench] task: {name} ({samples} samples)")
        for s in range(samples):
            r = run_one_sample(name, mod, s, model, timeout)
            results.append(r)
            mark = "PASS" if r.passed else "FAIL"
            print(f"  sample {s}: {mark} ({r.duration_seconds:.1f}s) — {r.detail}")
    finished = time.time()
    return RunReport(
        started_at=started,
        finished_at=finished,
        samples_per_task=samples,
        model=model,
        task_filter=task_filter,
        results=results,
    )


def _serialize_report(report: RunReport) -> Dict[str, Any]:
    return {
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "samples_per_task": report.samples_per_task,
        "model": report.model,
        "task_filter": report.task_filter,
        "results": [asdict(r) for r in report.results],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="monitor_bench", description="Run the monitor benchmark suite.")
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=None,
        help="Filter tasks by name or tag substring. Default: all.",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=3,
        help="Samples per task (default: 3). More samples = lower noise but linear cost.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Per-sample subprocess timeout in seconds (default: 600).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override the active model for the run (passes --model to monitor).",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Where to write the run JSON. Default: results/run-<timestamp>.json.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    RESULTS_DIR.mkdir(exist_ok=True)
    report = run(
        task_filter=args.tasks,
        samples=args.samples,
        timeout=args.timeout,
        model=args.model,
    )

    out_path = (
        Path(args.out)
        if args.out
        else RESULTS_DIR / f"run-{int(report.started_at)}.json"
    )
    out_path.write_text(json.dumps(_serialize_report(report), indent=2, sort_keys=True))
    print(f"\n[bench] wrote {out_path}")

    # Quick console summary so the user sees the headline number even
    # without running report.py. Full aggregation lives in report.py.
    n = len(report.results)
    passes = sum(1 for r in report.results if r.passed)
    print(f"[bench] {passes}/{n} samples passed ({(passes / n * 100) if n else 0:.0f}%)")
    return 0 if passes == n else 1


if __name__ == "__main__":
    sys.exit(main())
