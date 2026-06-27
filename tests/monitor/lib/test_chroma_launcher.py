"""Tests for the thin chroma-db launcher script."""

from __future__ import annotations

from pathlib import Path


def test_launcher_imports_main() -> None:
    """The launcher script should remain a thin wrapper around main()."""
    launcher_path = Path("bin/chroma-db")
    content = launcher_path.read_text(encoding="utf-8")

    assert "from monitor.lib.chroma_cli import main" in content
    assert "if __name__ == \"__main__\"" in content
