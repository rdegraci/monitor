"""Run a monitor_bench baseline/current workflow and optionally compare them.

This helper wraps the common benchmark loop of:
1. running a baseline benchmark,
2. running a second benchmark after a change,
3. invoking ``benchmark.monitor_bench.compare`` on the two result files.

It is intentionally lightweight and shells out to the existing runner and
compare entrypoints so the workflow stays aligned with the supported CLIs.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def _build_runner_command(
    *,
    label: str,
    output_path: Path,
    tasks: Optional[List[str]],
    samples: int,
    timeout: int,
    model: Optional[str],
    python_executable: str,
) -> List[str]:
    """Build the runner subprocess command.

    Args:
        label: Human-readable run label for diagnostics.
        output_path: Run JSON output path.
        tasks: Optional task filter values.
        samples: Samples per task.
        timeout: Per-sample timeout seconds.
        model: Optional model override.
        python_executable: Python executable used to spawn subprocesses.

    Returns:
        Argument vector for ``subprocess.run``.
    """
    command = [
        python_executable,
        "-m",
        "benchmark.monitor_bench.runner",
        "--samples",
        str(samples),
        "--timeout",
        str(timeout),
        "--out",
        str(output_path),
    ]
    if tasks:
        command.extend(["--tasks", *tasks])
    if model:
        command.extend(["--model", model])
    print(f"[workflow] {label} command: {shlex.join(command)}")
    return command


def _build_compare_command(
    *,
    before_path: Path,
    after_path: Path,
    compare_format: str,
    only_regressions: bool,
    show_unchanged: bool,
    sort_by: str,
    python_executable: str,
) -> List[str]:
    """Build the compare subprocess command.

    Args:
        before_path: Baseline run JSON path.
        after_path: Candidate run JSON path.
        compare_format: Compare output format.
        only_regressions: Whether to include only regressions.
        show_unchanged: Whether to include unchanged tasks.
        sort_by: Compare sort field.
        python_executable: Python executable used to spawn subprocesses.

    Returns:
        Argument vector for ``subprocess.run``.
    """
    command = [
        python_executable,
        "-m",
        "benchmark.monitor_bench.compare",
        str(before_path),
        str(after_path),
        "--format",
        compare_format,
        "--sort-by",
        sort_by,
    ]
    if only_regressions:
        command.append("--only-regressions")
    if show_unchanged:
        command.append("--show-unchanged")
    print(f"[workflow] compare command: {shlex.join(command)}")
    return command


def _run_command(command: List[str]) -> int:
    """Run a subprocess command and return its exit code.

    Args:
        command: Argument vector for the subprocess.

    Returns:
        Subprocess exit code.
    """
    completed = subprocess.run(command, check=False)
    return completed.returncode


def _validate_run_file(path: Path) -> None:
    """Validate that a run JSON file exists and parses.

    Args:
        path: Run JSON path expected from the runner.

    Raises:
        FileNotFoundError: If the path does not exist.
        json.JSONDecodeError: If the file does not contain valid JSON.
    """
    if not path.is_file():
        raise FileNotFoundError(f"expected run JSON at {path}")
    json.loads(path.read_text())


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for the baseline/current benchmark workflow helper.

    Args:
        argv: Optional CLI argument override.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(
        description="Run baseline/current monitor_bench workflow and compare results."
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=None,
        help="Optional task or tag filters passed through to the runner.",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=3,
        help="Samples per task for both runs.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Per-sample timeout in seconds for both runs.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Optional model override for both runs.",
    )
    parser.add_argument(
        "--baseline-out",
        type=Path,
        default=Path("benchmark/monitor_bench/results/workflow-baseline.json"),
        help="Where to write the baseline run JSON.",
    )
    parser.add_argument(
        "--candidate-out",
        type=Path,
        default=Path("benchmark/monitor_bench/results/workflow-candidate.json"),
        help="Where to write the candidate run JSON.",
    )
    parser.add_argument(
        "--skip-baseline",
        action="store_true",
        help="Reuse an existing baseline JSON instead of rerunning the baseline benchmark.",
    )
    parser.add_argument(
        "--skip-compare",
        action="store_true",
        help="Run the two benchmarks but do not invoke the compare helper.",
    )
    parser.add_argument(
        "--compare-format",
        choices=["text", "markdown", "json"],
        default="text",
        help="Output format to use when invoking compare.",
    )
    parser.add_argument(
        "--only-regressions",
        action="store_true",
        help="Pass --only-regressions to the compare helper.",
    )
    parser.add_argument(
        "--show-unchanged",
        action="store_true",
        help="Pass --show-unchanged to the compare helper.",
    )
    parser.add_argument(
        "--sort-by",
        choices=["pass", "cost", "tools", "loops", "duration"],
        default="pass",
        help="Sort field to use when invoking compare.",
    )
    args = parser.parse_args(argv)

    args.baseline_out.parent.mkdir(parents=True, exist_ok=True)
    args.candidate_out.parent.mkdir(parents=True, exist_ok=True)

    if not args.skip_baseline:
        baseline_command = _build_runner_command(
            label="baseline",
            output_path=args.baseline_out,
            tasks=args.tasks,
            samples=args.samples,
            timeout=args.timeout,
            model=args.model,
            python_executable=sys.executable,
        )
        baseline_code = _run_command(baseline_command)
        if baseline_code != 0:
            print(f"[workflow] baseline run exited with {baseline_code}")
            return baseline_code
    else:
        print(f"[workflow] reusing baseline JSON: {args.baseline_out}")

    candidate_command = _build_runner_command(
        label="candidate",
        output_path=args.candidate_out,
        tasks=args.tasks,
        samples=args.samples,
        timeout=args.timeout,
        model=args.model,
        python_executable=sys.executable,
    )
    candidate_code = _run_command(candidate_command)
    if candidate_code != 0:
        print(f"[workflow] candidate run exited with {candidate_code}")
        return candidate_code

    try:
        _validate_run_file(args.baseline_out)
        _validate_run_file(args.candidate_out)
    except (FileNotFoundError, json.JSONDecodeError) as error:
        print(f"[workflow] {error}")
        return 1

    print(f"[workflow] baseline JSON:  {args.baseline_out}")
    print(f"[workflow] candidate JSON: {args.candidate_out}")

    if args.skip_compare:
        return 0

    compare_command = _build_compare_command(
        before_path=args.baseline_out,
        after_path=args.candidate_out,
        compare_format=args.compare_format,
        only_regressions=args.only_regressions,
        show_unchanged=args.show_unchanged,
        sort_by=args.sort_by,
        python_executable=sys.executable,
    )
    return _run_command(compare_command)


if __name__ == "__main__":
    sys.exit(main())
