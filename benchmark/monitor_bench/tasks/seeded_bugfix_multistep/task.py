"""Seeded multi-file bugfix task.

The workspace contains a small value-flow bug spread across multiple files.
Monitor must inspect the files, understand why the configured prefix is not
used, and fix the issue.
"""

from __future__ import annotations

from pathlib import Path

NAME = "seeded_bugfix_multistep"
TAGS = ["edit", "bugfix", "multistep", "seeded"]
PROMPT = (
    'Investigate why greet("Ada") does not use the configured default prefix '
    "and fix the problem."
)


def setup(workspace):
    """Seed a tiny multi-file workspace with a config-flow bug."""
    workspace = Path(workspace)
    (workspace / "config.py").write_text('DEFAULT_PREFIX = "Hello"\n')
    (workspace / "formatter.py").write_text(
        "def build_message(prefix: str, name: str) -> str:\n"
        '    return f"{prefix}, {name}!"\n'
    )
    (workspace / "app.py").write_text(
        "from config import DEFAULT_PREFIX\n"
        "from formatter import build_message\n\n"
        "def greet(name: str) -> str:\n"
        '    return build_message("Hi", name)\n'
    )
    (workspace / "expected.txt").write_text('greet("Ada") should return Hello, Ada!\n')


def grade(workspace, metrics, stdout, stderr, exit_code, history=None):
    """Pass if greet uses the configured default prefix after the fix."""
    if exit_code != 0:
        return False, f"non-zero exit: {exit_code}"
    if metrics is None:
        return False, "no metrics"

    app_text = (Path(workspace) / "app.py").read_text()
    if "build_message(DEFAULT_PREFIX, name)" not in app_text:
        return False, "app.py does not route greet() through build_message(DEFAULT_PREFIX, name)"
    if 'build_message("Hi", name)' in app_text:
        return False, "app.py still hardcodes the old prefix"
    return True, "greet uses the configured default prefix"
