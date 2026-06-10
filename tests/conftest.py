"""Test collection bootstrap for import path setup, safe monkeypatches, and unique pytest module names."""

import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    sys.path.insert(0, str(path))

# Safety monkeypatch for all tests
sys.modules["litellm"] = MagicMock()


@pytest.fixture
def short_tmp_path():
    """A short-rooted temp dir for binding AF_UNIX sockets.

    macOS caps a socket path (``sun_path``) at ~104 bytes. pytest's built-in
    ``tmp_path`` lives under ``/var/folders/.../T/...`` (deep enough to overflow
    that), so ``bind()`` raises ``OSError: AF_UNIX path too long``. Linux escapes
    it only because its temp base (``/tmp``) is short and its limit is 108 —
    hence the failures are Mac-only. Bind sockets under this short base instead.
    """
    base = "/tmp" if os.path.isdir("/tmp") else tempfile.gettempdir()
    d = tempfile.mkdtemp(prefix="m", dir=base)
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)

# Duplicate basenames should be avoided via package-specific testpaths or unique test filenames rather than custom collection.
