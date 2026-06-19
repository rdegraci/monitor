"""Tests for Stage 3 phase-scoped escalation.

The orchestrator runs base MODEL and transiently swaps to ORCHESTRATOR_MODEL on
collation/synthesis turns (when sub-agent results are folded in), then backs down.
Covers the pure resolvers (resolve_turn_model priority, effective_turn_effort
floor) and the conversation flag-set on fold.
"""

import monitor.config  # noqa: F401 — break import cycle
from monitor.lib.llm_model_utils import resolve_turn_model, effective_turn_effort

PREFIX = "openai/gpt-5"
BASE = "openai/gpt-5.4-mini-2026-03-17"
ORCH = "openai/gpt-5.4-2026-03-05"
ADV = "openai/gpt-5.4-2026-03-05"


# --- resolve_turn_model priority -------------------------------------------

def test_collation_swaps_to_orchestrator_model():
    assert resolve_turn_model(BASE, None, False, PREFIX,
                              orchestrator_model=ORCH, collation_active=True) == ORCH


def test_collation_takes_priority_over_override():
    # both active → collation/orchestrator wins over the reasoning-override/ADV
    assert resolve_turn_model(BASE, ADV, True, PREFIX,
                              orchestrator_model=ORCH, collation_active=True) == ORCH


def test_override_without_collation_uses_adv():
    assert resolve_turn_model(BASE, ADV, True, PREFIX,
                              orchestrator_model=ORCH, collation_active=False) == ADV


def test_no_collation_no_override_uses_base():
    assert resolve_turn_model(BASE, ADV, False, PREFIX,
                              orchestrator_model=ORCH, collation_active=False) == BASE


def test_collation_unset_orchestrator_uses_base():
    assert resolve_turn_model(BASE, None, False, PREFIX,
                              orchestrator_model=None, collation_active=True) == BASE


def test_collation_non_reasoning_orchestrator_uses_base():
    assert resolve_turn_model(BASE, None, False, PREFIX,
                              orchestrator_model="anthropic/claude-sonnet-4-6",
                              collation_active=True) == BASE


def test_collation_orchestrator_equal_base_no_swap():
    assert resolve_turn_model(BASE, None, False, PREFIX,
                              orchestrator_model=BASE, collation_active=True) == BASE


# --- effective_turn_effort -------------------------------------------------

def test_effort_collation_floors_to_orchestrator():
    assert effective_turn_effort("low", None, collation_active=True,
                                 orchestrator_effort="medium") == "medium"


def test_effort_collation_never_downgrades_override():
    # override "high" beats a lower orchestrator floor on a collation turn
    assert effective_turn_effort("low", "high", collation_active=True,
                                 orchestrator_effort="medium") == "high"


def test_effort_no_collation_uses_override_or_steady():
    assert effective_turn_effort("low", "high", collation_active=False,
                                 orchestrator_effort="medium") == "high"
    assert effective_turn_effort("low", None, collation_active=False,
                                 orchestrator_effort="medium") == "low"


def test_effort_collation_without_orchestrator_effort():
    assert effective_turn_effort("low", None, collation_active=True,
                                 orchestrator_effort=None) == "low"


# --- conversation fold sets the collation flag -----------------------------

def test_fold_sets_collation_flag_when_injections(monkeypatch):
    from monitor import config
    from monitor.core import conversation
    from monitor.lib import agent_orchestrator
    monkeypatch.setattr(config, "CURRENT_TURN_IS_COLLATION", False, raising=False)
    monkeypatch.setattr(config, "PENDING_LLM_PREFIXES", [], raising=False)
    monkeypatch.setattr(agent_orchestrator, "drain_pending_injections",
                        lambda: ["Background sub-agent 'a' finished: done"])
    monkeypatch.setattr(agent_orchestrator, "drain_pending_usage", lambda: [])
    conversation._fold_agent_injections_into_prefixes()
    assert config.CURRENT_TURN_IS_COLLATION is True


def test_fold_no_injections_leaves_flag_false(monkeypatch):
    from monitor import config
    from monitor.core import conversation
    from monitor.lib import agent_orchestrator
    monkeypatch.setattr(config, "CURRENT_TURN_IS_COLLATION", False, raising=False)
    monkeypatch.setattr(config, "PENDING_LLM_PREFIXES", [], raising=False)
    monkeypatch.setattr(agent_orchestrator, "drain_pending_injections", lambda: [])
    monkeypatch.setattr(agent_orchestrator, "drain_pending_usage", lambda: [])
    conversation._fold_agent_injections_into_prefixes()
    assert config.CURRENT_TURN_IS_COLLATION is False
