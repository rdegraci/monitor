"""Tests for role-based model selection (config.apply_role_model_override).

Stage 1 of smart orchestration. The resolver picks SUBAGENT_* (agent process) or
ORCHESTRATOR_* (orchestrator) and applies the model via set_model + the effort.
set_model is spied so these isolate the role-resolution logic from set_model's
heavy internals (tested elsewhere).
"""

import monitor.config  # noqa: F401 — break import cycle
from monitor import config


def _base(monkeypatch):
    monkeypatch.setattr(config, "MODEL", "openai/gpt-5.4-mini-2026-03-17", raising=False)
    monkeypatch.setattr(config, "REASONING_EFFORT", "medium", raising=False)
    monkeypatch.setattr(config, "AGENT", False, raising=False)
    monkeypatch.setattr(config, "MONITOR_ENABLE_AGENT_ORCHESTRATION", False, raising=False)
    monkeypatch.setattr(config, "ORCHESTRATOR_MODEL", None, raising=False)
    monkeypatch.setattr(config, "ORCHESTRATOR_REASONING_EFFORT", None, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_MODEL", None, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_REASONING_EFFORT", None, raising=False)


def _spy_set_model(monkeypatch, *, ok=True):
    calls = []

    def fake(key):
        calls.append(key)
        if ok:
            config.MODEL = key
        return ok

    monkeypatch.setattr(config, "set_model", fake, raising=False)
    return calls


def test_agent_role_uses_subagent_model_and_effort(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_MODEL", "openai/gpt-5.4-2026-03-05", raising=False)
    monkeypatch.setattr(config, "SUBAGENT_REASONING_EFFORT", "high", raising=False)
    calls = _spy_set_model(monkeypatch)
    config.apply_role_model_override()
    assert calls == ["openai/gpt-5.4-2026-03-05"]
    assert config.REASONING_EFFORT == "high"


def test_orchestrator_role_uses_orchestrator_model_and_effort(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(config, "MONITOR_ENABLE_AGENT_ORCHESTRATION", True, raising=False)
    monkeypatch.setattr(config, "ORCHESTRATOR_MODEL", "openai/gpt-5.4-2026-03-05", raising=False)
    monkeypatch.setattr(config, "ORCHESTRATOR_REASONING_EFFORT", "low", raising=False)
    calls = _spy_set_model(monkeypatch)
    config.apply_role_model_override()
    assert calls == ["openai/gpt-5.4-2026-03-05"]
    assert config.REASONING_EFFORT == "low"


def test_agent_takes_precedence_over_orchestration(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "MONITOR_ENABLE_AGENT_ORCHESTRATION", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_MODEL", "openai/gpt-5.4-2026-03-05", raising=False)
    monkeypatch.setattr(config, "ORCHESTRATOR_MODEL", "openai/should-not-be-used", raising=False)
    calls = _spy_set_model(monkeypatch)
    config.apply_role_model_override()
    assert calls == ["openai/gpt-5.4-2026-03-05"]  # subagent, not orchestrator


def test_no_role_is_noop(monkeypatch):
    _base(monkeypatch)
    # Orchestrator model set but orchestration disabled and not an agent → no role.
    monkeypatch.setattr(config, "ORCHESTRATOR_MODEL", "openai/gpt-5.4-2026-03-05", raising=False)
    calls = _spy_set_model(monkeypatch)
    config.apply_role_model_override()
    assert calls == []
    assert config.REASONING_EFFORT == "medium"


def test_unset_role_model_still_applies_effort(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_MODEL", None, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_REASONING_EFFORT", "high", raising=False)
    calls = _spy_set_model(monkeypatch)
    config.apply_role_model_override()
    assert calls == []                       # no model switch
    assert config.REASONING_EFFORT == "high"  # effort still applied


def test_role_model_equal_to_active_skips_switch(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_MODEL", "openai/gpt-5.4-mini-2026-03-17", raising=False)  # == MODEL
    calls = _spy_set_model(monkeypatch)
    config.apply_role_model_override()
    assert calls == []


def test_unresolvable_model_keeps_base(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_MODEL", "openai/bogus-undated", raising=False)
    calls = _spy_set_model(monkeypatch, ok=False)  # set_model rejects unknown
    config.apply_role_model_override()
    assert calls == ["openai/bogus-undated"]
    assert config.MODEL == "openai/gpt-5.4-mini-2026-03-17"  # unchanged


def test_invalid_effort_ignored(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_REASONING_EFFORT", "turbo", raising=False)
    _spy_set_model(monkeypatch)
    config.apply_role_model_override()
    assert config.REASONING_EFFORT == "medium"  # unchanged
