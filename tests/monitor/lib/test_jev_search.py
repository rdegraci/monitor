"""Tests for Jev search top-K Score reorder."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from monitor.lib import jev_search as jsearch


@pytest.fixture(autouse=True)
def _clear_jev_env(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("MONITOR_JEV", raising=False)
    monkeypatch.delenv("MONITOR_JEV_CONFIDENCE", raising=False)


def test_search_disabled_lexical_only():
    stdout = "a.py\n1: foo\n\nb.py\n1: bar\n"
    out = jsearch.rerank_rg_output_with_jev(stdout, "foo bar")
    assert "a.py" in out or "b.py" in out


@patch("monitor.lib.jev_search.tc.system_one")
def test_search_jev_reorders(mock_system_one, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    monkeypatch.setenv("MONITOR_JEV_CONFIDENCE", "0.5")
    stdout = "noise.py\n1: unrelated\n\nhit.py\n1: target symbol\n"
    mock_system_one.return_value = {
        "answers": {
            "blk_0": {"type": "score", "score": 0.5, "confidence": 0.9},
            "blk_1": {"type": "score", "score": 2.8, "confidence": 0.9},
        }
    }
    out = jsearch.rerank_rg_output_with_jev(stdout, "target symbol")
    assert out.find("hit.py") < out.find("noise.py") or "hit.py" in out
