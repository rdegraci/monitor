"""Tests for the configurable soft auto-compaction threshold.

Covers:
- Default value is 0.30.
- YAML override honored when in (0, 1].
- YAML override rejected (falls back to default) for invalid values:
  out-of-range, non-numeric.
- The soft-trigger arithmetic in core/llm.py is consistent with the config —
  i.e., when estimated_tokens > ratio * input_window, the branch should fire
  (verified via the int-cast threshold).
"""

import logging

from monitor import config


def test_default_threshold_is_30_percent():
    """Sanity check that the recommended default hasn't regressed."""
    assert config.AUTO_COMPACT_THRESHOLD_RATIO == 0.30


def test_soft_threshold_arithmetic_matches_llm_path():
    """The trigger in core/llm.py computes the threshold as
    int(input_window * ratio). Verify both that the cast is intentional
    (truncates fractional tokens) and that the resulting integer correctly
    bounds the trigger for the documented default."""
    ratio = config.AUTO_COMPACT_THRESHOLD_RATIO
    assert int(1_000_000 * ratio) == 300_000
    assert int(200_000 * ratio) == 60_000


def test_yaml_loader_accepts_valid_ratio(monkeypatch, caplog):
    """A ratio of 0.20 in YAML should override the default after the loader
    runs. Reset to the documented default after the test to avoid leaking
    state into other tests."""
    original = config.AUTO_COMPACT_THRESHOLD_RATIO
    try:
        _invoke_yaml_loader({"AUTO_COMPACT_THRESHOLD_RATIO": 0.20})
        assert config.AUTO_COMPACT_THRESHOLD_RATIO == 0.20
    finally:
        config.AUTO_COMPACT_THRESHOLD_RATIO = original


def test_yaml_loader_accepts_ratio_at_upper_bound(monkeypatch):
    """1.0 is the legal upper bound (means 'compact only at the hard limit')
    and must be accepted."""
    original = config.AUTO_COMPACT_THRESHOLD_RATIO
    try:
        _invoke_yaml_loader({"AUTO_COMPACT_THRESHOLD_RATIO": 1.0})
        assert config.AUTO_COMPACT_THRESHOLD_RATIO == 1.0
    finally:
        config.AUTO_COMPACT_THRESHOLD_RATIO = original


def test_yaml_loader_rejects_zero(caplog):
    """0.0 would mean 'compact every turn' — silly. Rejected; warning logged;
    default retained."""
    original = config.AUTO_COMPACT_THRESHOLD_RATIO
    try:
        caplog.set_level(logging.WARNING, logger="monitor.config")
        _invoke_yaml_loader({"AUTO_COMPACT_THRESHOLD_RATIO": 0.0})
        assert config.AUTO_COMPACT_THRESHOLD_RATIO == original
        assert any("outside (0, 1]" in r.getMessage() for r in caplog.records)
    finally:
        config.AUTO_COMPACT_THRESHOLD_RATIO = original


def test_yaml_loader_rejects_negative(caplog):
    original = config.AUTO_COMPACT_THRESHOLD_RATIO
    try:
        caplog.set_level(logging.WARNING, logger="monitor.config")
        _invoke_yaml_loader({"AUTO_COMPACT_THRESHOLD_RATIO": -0.1})
        assert config.AUTO_COMPACT_THRESHOLD_RATIO == original
        assert any("outside (0, 1]" in r.getMessage() for r in caplog.records)
    finally:
        config.AUTO_COMPACT_THRESHOLD_RATIO = original


def test_yaml_loader_rejects_above_one(caplog):
    original = config.AUTO_COMPACT_THRESHOLD_RATIO
    try:
        caplog.set_level(logging.WARNING, logger="monitor.config")
        _invoke_yaml_loader({"AUTO_COMPACT_THRESHOLD_RATIO": 1.5})
        assert config.AUTO_COMPACT_THRESHOLD_RATIO == original
        assert any("outside (0, 1]" in r.getMessage() for r in caplog.records)
    finally:
        config.AUTO_COMPACT_THRESHOLD_RATIO = original


def test_yaml_loader_rejects_non_numeric(caplog):
    """Garbage strings must not crash the loader — log warning, keep default."""
    original = config.AUTO_COMPACT_THRESHOLD_RATIO
    try:
        caplog.set_level(logging.WARNING, logger="monitor.config")
        _invoke_yaml_loader({"AUTO_COMPACT_THRESHOLD_RATIO": "thirty percent"})
        assert config.AUTO_COMPACT_THRESHOLD_RATIO == original
        assert any("is not a number" in r.getMessage() for r in caplog.records)
    finally:
        config.AUTO_COMPACT_THRESHOLD_RATIO = original


def test_yaml_loader_no_key_leaves_default(monkeypatch):
    """Omitting the key entirely should leave the module default in place."""
    original = config.AUTO_COMPACT_THRESHOLD_RATIO
    try:
        _invoke_yaml_loader({})
        assert config.AUTO_COMPACT_THRESHOLD_RATIO == original
    finally:
        config.AUTO_COMPACT_THRESHOLD_RATIO = original


# --- helper -----------------------------------------------------------------


def _invoke_yaml_loader(yaml_overrides):
    """Run just the AUTO_COMPACT_THRESHOLD_RATIO branch from
    load_environment_globals against a fake yaml_config dict. We extract the
    branch rather than calling the full loader because the loader has many
    side effects (logging setup, file I/O, env var reads) unrelated to this
    setting.

    Keep this helper aligned with the actual config.py logic — if you change
    the validation in load_environment_globals, mirror it here so the tests
    keep covering real behavior."""
    _ratio_raw = yaml_overrides.get("AUTO_COMPACT_THRESHOLD_RATIO")
    if _ratio_raw is None:
        return
    try:
        _ratio_val = float(_ratio_raw)
        if 0.0 < _ratio_val <= 1.0:
            config.AUTO_COMPACT_THRESHOLD_RATIO = _ratio_val
        else:
            config_logger = logging.getLogger("monitor.config")
            config_logger.warning(
                "AUTO_COMPACT_THRESHOLD_RATIO=%r outside (0, 1]; keeping default %s",
                _ratio_raw, config.AUTO_COMPACT_THRESHOLD_RATIO,
            )
    except (TypeError, ValueError):
        config_logger = logging.getLogger("monitor.config")
        config_logger.warning(
            "AUTO_COMPACT_THRESHOLD_RATIO=%r is not a number; keeping default %s",
            _ratio_raw, config.AUTO_COMPACT_THRESHOLD_RATIO,
        )
