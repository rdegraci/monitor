"""Run a Python type checker (mypy or pyright) and return structured results.

Tool entry point: ``type_check_python``. Registered in tool_definitions.py.

Prefers mypy if available (more universal in Python ecosystem); falls back to
pyright if installed. Returns structured exit_code/summary/output so the
model can branch on "did types pass" without parsing prose.

Output is tail-truncated like run_python_tests — type errors and the count
summary cluster at the end of mypy/pyright output, so the tail is what the
model needs to see.

Read-only with respect to source: the checker analyzes but does not modify
files. (Cache files like .mypy_cache/ may be written.)
"""

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

# Roughly 2.5K tokens of output. Tail-preserving truncation.
MAX_OUTPUT_CHARS = 10000
DEFAULT_TIMEOUT_SECONDS = 120

SUPPORTED_CHECKERS = ("mypy", "pyright")


def type_check_python(path: str | None = None, checker: str | None = None, timeout_seconds: int | None = None):
    """Run mypy or pyright on ``path`` and return a structured result dict.

    Args:
        path: Path to check. Defaults to 'src/' when that directory exists in
            cwd, otherwise '.'.
        checker: Force a specific checker ('mypy' or 'pyright'). If omitted,
            prefers mypy, falls back to pyright. Returns an error if the
            chosen checker isn't installed.
        timeout_seconds: Process timeout (default 120).

    Returns:
        dict with keys:
          - exit_code (int|None): checker's exit code; None on timeout/launch failure.
          - summary (str): one-line status, e.g. "Found 3 errors in 2 files".
          - output (str): tail-truncated stdout+stderr.
          - truncated (bool): True if output was truncated.
          - checker (str): the checker that ran, or '' on dispatch failure.
          - command (list): the actual argv invoked.
    """
    cwd = os.getcwd()

    # Resolve which checker to use
    if checker is not None:
        if checker not in SUPPORTED_CHECKERS:
            return _error_result(
                f"unsupported checker {checker!r}; use one of {SUPPORTED_CHECKERS}",
                checker=str(checker),
            )
        bin_path = shutil.which(checker)
        if not bin_path:
            return _error_result(
                f"{checker} not found on PATH; install it with `pip install {checker}`",
                checker=checker,
            )
    else:
        mypy_path = shutil.which("mypy")
        pyright_path = shutil.which("pyright")
        if mypy_path:
            checker = "mypy"
            bin_path = mypy_path
        elif pyright_path:
            checker = "pyright"
            bin_path = pyright_path
        else:
            return _error_result(
                "neither mypy nor pyright found on PATH; install one with "
                "`pip install mypy` or `pip install pyright`",
                checker="",
            )

    if path is None:
        path = "src" if os.path.isdir(os.path.join(cwd, "src")) else "."

    if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    cmd = [bin_path, path]
    logger.info("Type-checking: %s (cwd=%s, timeout=%ss)", " ".join(cmd), cwd, timeout_seconds)

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge so error context stays in order
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
            "checker": checker,
            "command": cmd,
        }
    except (FileNotFoundError, OSError) as e:
        return {
            "exit_code": None,
            "summary": f"{checker} invocation failed",
            "output": str(e),
            "truncated": False,
            "checker": checker,
            "command": cmd,
        }

    output_raw = proc.stdout or ""
    output, truncated = _truncate(output_raw)
    return {
        "exit_code": proc.returncode,
        "summary": _extract_summary(output_raw, proc.returncode, checker),
        "output": output,
        "truncated": truncated,
        "checker": checker,
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


def _extract_summary(output: str, exit_code: int, checker: str) -> str:
    """Pull the checker's final summary line.

    mypy ends with one of:
      - "Success: no issues found in N source files"
      - "Found N errors in M files (checked N source files)"
    pyright ends with something like:
      - "0 errors, 0 warnings, 0 informations"
    """
    if not output:
        return f"no output (exit {exit_code})"
    tokens = ("error", "errors", "success", "no issues", "warning", "warnings")
    for line in reversed(output.splitlines()):
        s = line.strip()
        if not s:
            continue
        lower = s.lower()
        if any(tok in lower for tok in tokens):
            return s
    # Fallback: last non-empty line
    for line in reversed(output.splitlines()):
        s = line.strip()
        if s:
            return s
    return f"exit {exit_code}"


def _error_result(message: str, checker: str = ""):
    return {
        "exit_code": None,
        "summary": message,
        "output": message,
        "truncated": False,
        "checker": checker,
        "command": [],
    }
