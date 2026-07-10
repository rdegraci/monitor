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


# Mutable session/turn state on the `config` module. Tests (and the source they
# exercise) mutate these via DIRECT assignment — not always monkeypatch — which
# leaks into later tests and makes the suite order-dependent (e.g. one test sets
# config.MODEL = "ollama/..." or leaves SESSION_COST_USD non-zero, breaking the
# rate-limiter / token-accounting tests that run after it). The autouse fixture
# below snapshots these before each test and restores them after, keeping tests
# hermetic regardless of run order. Config lookup TABLES (MODEL_MAPPING, pricing)
# are deliberately excluded — they're loaded once and tests that need them set
# them per-test.
_ISOLATED_CONFIG_ATTRS = (
    "MODEL", "ADV_REASONING_MODEL", "ORCHESTRATOR_MODEL", "REASONING_MODEL_PREFIX",
    "REASONING_EFFORT", "CURRENT_TURN_REASONING_OVERRIDE", "CURRENT_TURN_IS_COLLATION",
    "MODEL_MAX_TPM", "MODEL_CONTEXT_WINDOW", "MODEL_OUTPUT_WINDOW",
    "MODEL_INPUT_WINDOW", "MODEL_INPUT_TIER",
    "SESSION_COST_USD", "SESSION_TOTAL_TOKENS", "TOTAL_TOKEN_COUNT",
    "SESSION_CALIBRATION_BY_MODEL", "LAST_REQUEST_TOKEN_COUNT",
    "LAST_REQUEST_USED_ESTIMATE",
    "TURN_COSTS_USD", "TURN_ROUND_TRIPS", "TURN_CACHED_INPUT_TOKENS",
    "TURN_UNCACHED_INPUT_TOKENS", "TURN_OUTPUT_TOKENS",
    "SESSION_COMPACTION_COUNT", "SESSION_TOOL_CALL_COUNT", "SESSION_LOOP_DETECTOR_TRIPS",
    "LAST_BILLED_INPUT_TOKENS", "SESSION_TIER_CROSSINGS", "SESSION_RESPONSES_REQUESTS",
)


@pytest.fixture(autouse=True)
def _isolate_config_session_state():
    """Restore mutable session/turn config globals after each test (see above)."""
    import copy

    try:
        from monitor import config
    except Exception:
        yield
        return

    _MISSING = object()
    snapshot = {}
    for name in _ISOLATED_CONFIG_ATTRS:
        val = getattr(config, name, _MISSING)
        if val is _MISSING:
            continue
        try:
            snapshot[name] = copy.deepcopy(val)
        except Exception:
            snapshot[name] = val
    try:
        yield
    finally:
        for name, val in snapshot.items():
            try:
                setattr(config, name, val)
            except Exception:
                pass


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
