"""Test collection bootstrap for import path setup, safe monkeypatches, and unique pytest module names."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    sys.path.insert(0, str(path))

# Safety monkeypatch for all tests
sys.modules["litellm"] = MagicMock()

# Duplicate basenames should be avoided via package-specific testpaths or unique test filenames rather than custom collection.
