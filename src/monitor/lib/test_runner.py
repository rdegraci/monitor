"""Run pytest from the current working directory and return structured results.

Tool entry point: ``run_python_tests``. Registered in tool_definitions.py.

The tool is side-effect-aware (pytest can write files, touch databases, send
network requests) and shell-injection-safe (subprocess args=list, no shell=True).

Output budget: pytest output is tail-truncated to MAX_OUTPUT_CHARS — failures
and the final summary line cluster at the bottom of pytest output, so the
tail is what the model needs to see.
"""

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

# Roughly 2.5K tokens of output. Tail-preserving truncation.
MAX_OUTPUT_CHARS = 10000
DEFAULT_TIMEOUT_SECONDS = 120


def run_python_tests(path: str | None = None, pytest_args: list | None = None, timeout_seconds: int | None = None):
    """Run pytest in the current working directory and return a structured result dict.

    Args:
        path: Optional path or pattern to scope the test run (e.g.
            'tests/monitor/lib/test_foo.py' or
            'tests/monitor/lib/test_foo.py::TestFoo::test_bar'). If omitted,
            defaults to 'tests/' when that directory exists, otherwise '.'.
        pytest_args: Optional list of additional pytest CLI args (e.g.
            ['-k', 'test_foo', '-x']). Leading '-' is required for flags.
        timeout_seconds: Process timeout (default 120).

    Returns:
        dict with keys:
          - exit_code (int|None): pytest's exit code; None on timeout/launch failure.
          - summary (str): short status line, e.g. "13 passed, 1 failed in 0.42s".
          - output (str): stdout+stderr, tail-truncated to MAX_OUTPUT_CHARS.
          - truncated (bool): True if output was truncated.
          - command (list): the actual argv pytest was invoked with.
    """
    cwd = os.getcwd()

    pytest_bin = shutil.which("pytest")
    if not pytest_bin:
        return {
            "exit_code": None,
            "summary": "pytest not found on PATH",
            "output": (
                "pytest is not available in the current environment. "
                "Install it with `pip install pytest` (or activate the venv where it lives)."
            ),
            "truncated": False,
            "command": [],
        }

    if path is None:
        path = "tests" if os.path.isdir(os.path.join(cwd, "tests")) else "."

    if pytest_args is None:
        pytest_args = []
    if not isinstance(pytest_args, list):
        return {
            "exit_code": None,
            "summary": "invalid pytest_args (must be a list of strings)",
            "output": f"pytest_args must be a list; got {type(pytest_args).__name__}",
            "truncated": False,
            "command": [],
        }
    pytest_args = [str(a) for a in pytest_args]

    if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    cmd = [pytest_bin, "-q", path] + pytest_args
    logger.info("Running tests: %s (cwd=%s, timeout=%ss)", " ".join(cmd), cwd, timeout_seconds)

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge so failures stay in order
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        partial = e.output if isinstance(e.output, str) else ""
        return {
            "exit_code": None,
            "summary": f"timed out after {timeout_seconds}s",
            "output": _truncate(partial)[0],
            "truncated": len(partial) > MAX_OUTPUT_CHARS,
            "command": cmd,
        }
    except (FileNotFoundError, OSError) as e:
        return {
            "exit_code": None,
            "summary": "pytest invocation failed",
            "output": str(e),
            "truncated": False,
            "command": cmd,
        }

    output_raw = proc.stdout or ""
    output, truncated = _truncate(output_raw)
    return {
        "exit_code": proc.returncode,
        "summary": _extract_summary(output_raw, proc.returncode),
        "output": output,
        "truncated": truncated,
        "command": cmd,
    }


def _truncate(text: str):
    """Return (text_with_tail_preserved, was_truncated)."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return (
        f"... [output truncated; head omitted, last {MAX_OUTPUT_CHARS} chars below] ...\n"
        + text[-MAX_OUTPUT_CHARS:],
        True,
    )


def _extract_summary(output: str, exit_code: int) -> str:
    """Pull pytest's final summary line, e.g. '13 passed, 1 failed in 0.42s'."""
    if not output:
        return f"no output (exit {exit_code})"
    for line in reversed(output.splitlines()):
        s = line.strip().strip("=").strip()
        if any(tok in s for tok in ("passed", "failed", "error", "no tests ran", "collected")):
            return s or f"exit {exit_code}"
    return f"exit {exit_code}"
