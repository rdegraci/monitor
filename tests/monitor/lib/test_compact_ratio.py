"""Tests for the per-model auto-compaction ratio resolver
(config.effective_auto_compact_ratio + AUTO_COMPACT_THRESHOLD_RATIO_BY_MODEL).
"""

import monitor.config  # noqa: F401 — break import cycle
from monitor import config


def _set(monkeypatch, *, model, default, overrides):
    monkeypatch.setattr(config, "MODEL", model, raising=False)
    monkeypatch.setattr(config, "AUTO_COMPACT_THRESHOLD_RATIO", default, raising=False)
    monkeypatch.setattr(config, "AUTO_COMPACT_THRESHOLD_RATIO_BY_MODEL", overrides, raising=False)


def test_override_used_for_active_model(monkeypatch):
    _set(monkeypatch, model="openai/gpt-5.4-2026-03-05", default=0.50,
         overrides={"openai/gpt-5.4-2026-03-05": 0.12})
    assert config.effective_auto_compact_ratio() == 0.12


def test_unlisted_model_uses_default(monkeypatch):
    _set(monkeypatch, model="openai/gpt-5.4-mini-2026-03-17", default=0.50,
         overrides={"openai/gpt-5.4-2026-03-05": 0.12})
    assert config.effective_auto_compact_ratio() == 0.50


def test_explicit_model_arg_overrides_active(monkeypatch):
    _set(monkeypatch, model="openai/gpt-5.4-mini-2026-03-17", default=0.50,
         overrides={"openai/gpt-5.4-2026-03-05": 0.12})
    assert config.effective_auto_compact_ratio("openai/gpt-5.4-2026-03-05") == 0.12


def test_empty_overrides_uses_default(monkeypatch):
    _set(monkeypatch, model="m", default=0.50, overrides={})
    assert config.effective_auto_compact_ratio() == 0.50


def test_boundary_value_one_is_valid(monkeypatch):
    _set(monkeypatch, model="m", default=0.50, overrides={"m": 1.0})
    assert config.effective_auto_compact_ratio() == 1.0


def test_invalid_override_falls_back_to_default(monkeypatch):
    # 0 / negative / > 1 / non-numeric / bool all rejected → scalar default.
    for bad in (0, -0.1, 1.5, "x", True, None):
        _set(monkeypatch, model="m", default=0.50, overrides={"m": bad})
        assert config.effective_auto_compact_ratio() == 0.50, f"bad={bad!r}"


def test_non_dict_overrides_falls_back(monkeypatch):
    _set(monkeypatch, model="m", default=0.50, overrides="not-a-dict")
    assert config.effective_auto_compact_ratio() == 0.50
