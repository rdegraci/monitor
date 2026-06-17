"""Seeded multi-file refactor task with unchanged runtime behavior.

The workspace requires a tiny symbol rename across multiple files while
preserving behavior. This is the strongest minimal approximation of a
long-horizon coding task in the initial benchmark suite.
"""

from __future__ import annotations

from pathlib import Path

NAME = "plan_then_execute_refactor"
TAGS = ["planning", "edit", "long_horizon", "seeded"]
PROMPT = "Rename DISPLAY_NAME to APP_NAME everywhere it is used and keep behavior unchanged."


def setup(workspace):
    """Seed a tiny multi-file refactor workspace."""
    workspace = Path(workspace)
    (workspace / "constants.py").write_text('DISPLAY_NAME = "Monitor"\n')
    (workspace / "ui.py").write_text(
        "from constants import DISPLAY_NAME\n\n"
        "def heading() -> str:\n"
        "    return DISPLAY_NAME\n"
    )
    (workspace / "messages.py").write_text(
        "from constants import DISPLAY_NAME\n\n"
        "def welcome() -> str:\n"
        '    return f"Welcome to {DISPLAY_NAME}"\n'
    )
    (workspace / "task.txt").write_text(
        "Rename DISPLAY_NAME to APP_NAME everywhere it is used and keep behavior unchanged.\n"
    )


def grade(workspace, metrics, stdout, stderr, exit_code, history=None):
    """Pass if the rename is complete and behavior stays unchanged."""
    if exit_code != 0:
        return False, f"non-zero exit: {exit_code}"
    if metrics is None:
        return False, "no metrics"

    workspace = Path(workspace)
    py_files = sorted(workspace.glob("*.py"))
    remaining = []
    for path in py_files:
        text = path.read_text()
        if "DISPLAY_NAME" in text:
            remaining.append(path.name)
    if remaining:
        return False, f"DISPLAY_NAME still present in files: {remaining}"

    constants_text = (workspace / "constants.py").read_text()
    if "APP_NAME" not in constants_text:
        return False, "constants.py does not define APP_NAME"

    ui_text = (workspace / "ui.py").read_text()
    messages_text = (workspace / "messages.py").read_text()
    if "from constants import APP_NAME" not in ui_text:
        return False, "ui.py does not import APP_NAME"
    if "return APP_NAME" not in ui_text:
        return False, "ui.py does not return APP_NAME"
    if "from constants import APP_NAME" not in messages_text:
        return False, "messages.py does not import APP_NAME"
    if 'return f"Welcome to {APP_NAME}"' not in messages_text:
        return False, "messages.py does not interpolate APP_NAME in welcome()"
    return True, "rename completed and behavior unchanged"
