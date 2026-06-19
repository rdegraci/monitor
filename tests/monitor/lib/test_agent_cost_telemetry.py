"""Tests for Stage 2 sub-agent cost telemetry (result-only, cost+tokens).

Covers the three new pieces: protocol `usage` sanitize/build, orchestrator
queue+drain of usage from RESULT frames, and config.record_agent_usage folding
into session totals + per-model calibration.
"""

import monitor.config  # noqa: F401 — break import cycle
from monitor import config
from monitor.lib import agent_protocol as ap
from monitor.lib import agent_orchestrator as orch
from monitor.lib import model_pricing


# --- protocol: sanitize_usage ----------------------------------------------

def test_sanitize_usage_valid_and_coerces():
    assert ap.sanitize_usage({"model": "m", "cost_usd": 0.02, "total_tokens": 500}) == \
        {"model": "m", "cost_usd": 0.02, "total_tokens": 500}
    # string-ish numerics coerce
    assert ap.sanitize_usage({"model": "m", "cost_usd": "0.02", "total_tokens": "500"}) == \
        {"model": "m", "cost_usd": 0.02, "total_tokens": 500}


def test_sanitize_usage_rejects_malformed():
    assert ap.sanitize_usage(None) is None
    assert ap.sanitize_usage("x") is None
    assert ap.sanitize_usage({"cost_usd": 1, "total_tokens": 1}) is None          # no model
    assert ap.sanitize_usage({"model": "", "cost_usd": 1, "total_tokens": 1}) is None
    assert ap.sanitize_usage({"model": "m", "cost_usd": "abc", "total_tokens": 1}) is None
    assert ap.sanitize_usage({"model": "m", "cost_usd": -1, "total_tokens": 1}) is None
    assert ap.sanitize_usage({"model": "m", "cost_usd": 1, "total_tokens": -5}) is None


# --- protocol: result frame -------------------------------------------------

def test_result_frame_includes_usage():
    f = ap.result("a", 1, ok=True, summary="s",
                  usage={"model": "m", "cost_usd": 0.01, "total_tokens": 100})
    assert f["body"]["usage"] == {"model": "m", "cost_usd": 0.01, "total_tokens": 100}


def test_result_frame_drops_malformed_or_absent_usage():
    f = ap.result("a", 1, ok=True, summary="s", usage={"cost_usd": 0.01})  # no model
    assert "usage" not in f["body"]
    f2 = ap.result("a", 1, ok=True, summary="s")
    assert "usage" not in f2["body"]


# --- orchestrator: queue + drain -------------------------------------------

def test_on_frame_queues_and_drains_usage():
    orch.drain_pending_usage()  # clear any prior
    frame = ap.result("agent-x", 1, ok=True, summary="done",
                      usage={"model": "openai/gpt-5.4-mini-2026-03-17",
                             "cost_usd": 0.02, "total_tokens": 5000})
    orch._on_frame(frame, conn_id=1)
    drained = orch.drain_pending_usage()
    assert drained == [{"model": "openai/gpt-5.4-mini-2026-03-17",
                        "cost_usd": 0.02, "total_tokens": 5000}]
    assert orch.drain_pending_usage() == []  # cleared


def test_on_frame_ignores_malformed_usage_block():
    orch.drain_pending_usage()
    # Build a RESULT frame with a raw malformed usage block (bypassing ap.result's
    # sanitize) to exercise the orchestrator's own sanitize-on-read.
    frame = ap.make_frame(ap.RESULT, "agent-z", 1,
                          {"ok": True, "summary": "x", "usage": {"cost_usd": 1.0}})  # no model
    orch._on_frame(frame, conn_id=2)
    assert orch.drain_pending_usage() == []


def test_on_frame_result_without_usage_is_fine():
    orch.drain_pending_usage()
    orch._on_frame(ap.result("agent-q", 1, ok=True, summary="x"), conn_id=3)
    assert orch.drain_pending_usage() == []


# --- config: record_agent_usage --------------------------------------------

def test_record_agent_usage_folds_into_session(monkeypatch):
    monkeypatch.setattr(config, "SESSION_COST_USD", 1.0, raising=False)
    monkeypatch.setattr(config, "SESSION_TOTAL_TOKENS", 1000, raising=False)
    monkeypatch.setattr(config, "SESSION_CALIBRATION_BY_MODEL", {}, raising=False)

    config.record_agent_usage({"model": "sub/m", "cost_usd": 0.5, "total_tokens": 2000})

    assert config.SESSION_COST_USD == 1.5
    assert config.SESSION_TOTAL_TOKENS == 3000
    entry = model_pricing.calibration_entry("sub/m")
    assert entry["cost_usd"] == 0.5
    assert entry["total_tokens"] == 2000


def test_record_agent_usage_accumulates_two_results(monkeypatch):
    monkeypatch.setattr(config, "SESSION_COST_USD", 0.0, raising=False)
    monkeypatch.setattr(config, "SESSION_TOTAL_TOKENS", 0, raising=False)
    monkeypatch.setattr(config, "SESSION_CALIBRATION_BY_MODEL", {}, raising=False)

    config.record_agent_usage({"model": "sub/m", "cost_usd": 0.10, "total_tokens": 100})
    config.record_agent_usage({"model": "sub/m", "cost_usd": 0.20, "total_tokens": 300})

    assert config.SESSION_COST_USD == pytest_approx(0.30)
    assert config.SESSION_TOTAL_TOKENS == 400
    entry = model_pricing.calibration_entry("sub/m")
    assert entry["cost_usd"] == pytest_approx(0.30)
    assert entry["total_tokens"] == 400


def test_record_agent_usage_ignores_malformed_and_zero(monkeypatch):
    monkeypatch.setattr(config, "SESSION_COST_USD", 1.0, raising=False)
    monkeypatch.setattr(config, "SESSION_TOTAL_TOKENS", 1000, raising=False)
    monkeypatch.setattr(config, "SESSION_CALIBRATION_BY_MODEL", {}, raising=False)

    config.record_agent_usage("nope")
    config.record_agent_usage({"model": "m"})                       # no cost/tokens → 0/0
    config.record_agent_usage({"model": "m", "cost_usd": 0, "total_tokens": 0})

    assert config.SESSION_COST_USD == 1.0     # unchanged
    assert config.SESSION_TOTAL_TOKENS == 1000


def pytest_approx(v):
    import pytest
    return pytest.approx(v)
