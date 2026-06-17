"""Seeded single-file bugfix task.

The workspace contains a tiny Python module with a formatting bug. Monitor is
expected to fix the function so it uses underscore separators for thousands.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

NAME = "seeded_bugfix_simple"
TAGS = ["edit", "bugfix", "seeded"]
PROMPT = "Fix the bug in math_utils.py so that format_total(1200) returns 1_200."


def setup(workspace):
    """Seed a tiny one-file workspace with an obvious formatting bug."""
    workspace = Path(workspace)
    (workspace / "math_utils.py").write_text(
        "def format_total(value: int) -> str:\n"
        "    return str(value)\n"
    )
    (workspace / "expected.txt").write_text(
        "format_total(1200) should return 1_200\n"
    )


def _load_module(path: Path):
    """Load a Python module from the given file path."""
    spec = importlib.util.spec_from_file_location("bench_math_utils", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def grade(workspace, metrics, stdout, stderr, exit_code, history=None):
    """Pass if format_total returns the expected underscore-separated string."""
    if exit_code != 0:
        return False, f"non-zero exit: {exit_code}"
    if metrics is None:
        return False, "no metrics"

    module = _load_module(Path(workspace) / "math_utils.py")
    actual = module.format_total(1200)
    if actual != "1_200":
        return False, f"expected format_total(1200) == '1_200', got {actual!r}"
    return True, "format_total returns underscore-separated thousands"
