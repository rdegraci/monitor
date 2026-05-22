"""Subprocess smoke tests for Monitor startup."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _write_minimal_monitor_config(tmp_path: Path) -> None:
    monitor_config_dir = tmp_path / "Library" / "Application Support" / "monitor"
    monitor_config_dir.mkdir(parents=True, exist_ok=True)
    (monitor_config_dir / "function_keys.json").write_text(json.dumps({}), encoding="utf-8")


def test_monitor_models_starts_without_traceback(tmp_path: Path) -> None:
    """Verify the Monitor CLI starts and lists models without a traceback."""
    _write_minimal_monitor_config(tmp_path)

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    result = subprocess.run(
        [sys.executable, "-m", "monitor", "--models"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        cwd=str(Path.cwd()),
        check=False,
    )

    assert result.returncode == 0
    assert "Available models" in result.stdout
    assert "Traceback" not in result.stderr
