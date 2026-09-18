"""Unit tests for BM25 indexing and search ranking helpers."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import monitor.config  # noqa: F401 — break import cycle for ripgrep_search

from monitor.lib import bm25, search_rank, ripgrep_search


@pytest.fixture(autouse=True)
def _clear_bm25_cache():
    bm25.clear_bm25_cache()
    yield
    bm25.clear_bm25_cache()


def test_tokenize_splits_camel_and_snake():
    tokens = bm25.tokenize("RedisTimeout redis_timeout")
    assert "redis" in tokens
    assert "timeout" in tokens
    assert "redistimeout" in tokens
    assert "redis_timeout" in tokens


def test_bm25_ranks_relevant_doc_first(tmp_path: Path):
    (tmp_path / "auth.py").write_text("def login():\n    check_password()\n", encoding="utf-8")
    (tmp_path / "weather.py").write_text("def forecast():\n    return rain\n", encoding="utf-8")
    (tmp_path / "session.py").write_text(
        "login session cookie auth password\n", encoding="utf-8"
    )

    listed = [
        str(tmp_path / "auth.py"),
        str(tmp_path / "weather.py"),
        str(tmp_path / "session.py"),
    ]
    with patch.object(bm25, "_list_source_files", return_value=listed):
        index = bm25.build_bm25_index(str(tmp_path), exclude_patterns=[])

    scores = index.score("login password auth")
    assert scores, "expected at least one scored document"
    assert scores[0][0].endswith("session.py") or scores[0][0].endswith("auth.py")
    assert not scores[0][0].endswith("weather.py")


def test_is_topical_query_routing():
    assert search_rank.is_topical_query("timeout redis reconnect") is True
    assert search_rank.is_topical_query("ClassName") is False
    assert search_rank.is_topical_query("foo bar", regex=True) is False
    assert search_rank.is_topical_query("ERR_TIMEOUT") is False


def test_rerank_rg_output_puts_better_file_first():
    stdout = (
        "noise.py\n"
        "1: unrelated hello\n"
        "\n"
        "target.py\n"
        "1: timeout redis reconnect handler\n"
        "2: redis client timeout\n"
    )
    ranked = search_rank.rerank_rg_output(stdout, "timeout redis")
    assert "target.py" in ranked
    assert ranked.index("target.py") < ranked.index("noise.py")


def test_rerank_classic_path_line_format():
    stdout = (
        "noise.py:10: hello world\n"
        "target.py:3: timeout redis reconnect\n"
        "target.py:4: more redis timeout\n"
    )
    ranked = search_rank.rerank_rg_output(stdout, "timeout redis")
    first_line = ranked.splitlines()[0]
    assert first_line.startswith("target.py:")


def test_exact_query_still_single_rg_call():
    """Single-token queries must not take the BM25 shortlist path."""
    with patch.object(ripgrep_search.subprocess, "run") as mock_run:
        mock_run.return_value = MagicMock(stdout="a.py:1: ClassName\n", stderr="", returncode=0)
        out = ripgrep_search.ripgrep_search("ClassName", use_default_excludes=False)

    assert "ClassName" in out
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert "-F" in cmd
    assert "ClassName" in cmd


def test_topical_query_uses_shortlist_when_index_available(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hit.py").write_text("timeout redis reconnect logic\n", encoding="utf-8")
    (tmp_path / "miss.py").write_text("unrelated content\n", encoding="utf-8")

    index = bm25.Bm25Index(root=str(tmp_path))
    index.add_document("hit.py", (tmp_path / "hit.py").read_text(encoding="utf-8"))
    index.add_document("miss.py", (tmp_path / "miss.py").read_text(encoding="utf-8"))
    index.finalize()

    with patch.object(ripgrep_search, "get_bm25_index", return_value=index):
        with patch.object(ripgrep_search, "_invoke_ripgrep") as mock_invoke:
            mock_invoke.return_value = "hit.py\n1: timeout redis reconnect logic\n"
            out = ripgrep_search.ripgrep_search(
                "timeout redis reconnect", use_default_excludes=False
            )

    assert "hit.py" in out
    mock_invoke.assert_called()
    kwargs = mock_invoke.call_args.kwargs
    targets = kwargs.get("search_targets") or []
    assert any(str(t).endswith("hit.py") for t in targets)
    assert not any(str(t) == "." for t in targets)


def test_topical_falls_back_when_shortlist_weak():
    with patch.object(ripgrep_search, "get_bm25_index", return_value=None):
        with patch.object(ripgrep_search.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="full.py:1: timeout redis\n", stderr="", returncode=0
            )
            out = ripgrep_search.ripgrep_search(
                "timeout redis", use_default_excludes=False
            )

    assert "full.py" in out
    # Fallback full-tree search: one rg invocation on the directory.
    assert mock_run.call_count == 1
