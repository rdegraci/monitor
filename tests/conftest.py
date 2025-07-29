import sys
from unittest.mock import MagicMock

# Safety monkeypatch for all tests
sys.modules["litellm"] = MagicMock()