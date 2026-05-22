"""Tests for Monitor version wiring and startup imports."""

from monitor import app
from monitor.core import version


def test_version_module_exports_values() -> None:
    """Verify the version module exposes matching version constants."""
    assert version.VERSION == "1.0.0"
    assert version.__version__ == version.VERSION


def test_app_module_has_start_logging() -> None:
    """Verify the app module still has access to start_logging after imports."""
    assert hasattr(app, "start_logging")
