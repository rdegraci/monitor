"""list_indexed_sessions reconciles the per-instance index against live
screen sessions: dead entries (one-shot agent exited / killed / crashed) are
pruned and omitted, so :agent list self-heals instead of showing stale
'unknown' rows. Pruning is skipped when screen -ls can't be queried.
"""

import pytest

from monitor.lib.screen_handler import ScreenHandler


@pytest.fixture
def handler(tmp_path):
    return ScreenHandler(
        monitor_cmd=["python", "-m", "monitor"],
        base_log_dir=str(tmp_path / "logs"),
        base_meta_dir=str(tmp_path / "meta"),
    )


def _seed(handler, *names):
    handler.save_sessions_index([
        {"session_name": n, "created_at": f"t-{n}", "meta_path": None} for n in names
    ])


def test_dead_session_is_pruned_and_omitted(handler, monkeypatch):
    _seed(handler, "alive", "dead")
    # Only "alive" is live in screen -ls.
    monkeypatch.setattr(handler, "_live_session_tokens", lambda: {"alive": "12.alive"})

    listed = handler.list_indexed_sessions()
    names = [e["session_name"] for e in listed]
    assert names == ["alive"]
    assert listed[0]["state"] == "running"
    assert listed[0]["token"] == "12.alive"
    # The dead entry was pruned from the persisted index.
    assert [e["session_name"] for e in handler.load_sessions_index()] == ["alive"]


def test_all_dead_yields_empty_and_clears_index(handler, monkeypatch):
    _seed(handler, "g1", "g2")
    monkeypatch.setattr(handler, "_live_session_tokens", lambda: {})  # none live
    assert handler.list_indexed_sessions() == []
    assert handler.load_sessions_index() == []


def test_no_prune_when_screen_ls_unavailable(handler, monkeypatch):
    _seed(handler, "maybe")
    # screen -ls couldn't be run → liveness undetermined → do NOT prune.
    monkeypatch.setattr(handler, "_live_session_tokens", lambda: None)
    listed = handler.list_indexed_sessions()
    assert [e["session_name"] for e in listed] == ["maybe"]
    assert listed[0]["state"] == "unknown"
    assert [e["session_name"] for e in handler.load_sessions_index()] == ["maybe"]


def test_indices_renumber_after_pruning(handler, monkeypatch):
    _seed(handler, "a", "b", "c")
    monkeypatch.setattr(handler, "_live_session_tokens", lambda: {"a": "1.a", "c": "3.c"})
    listed = handler.list_indexed_sessions()
    assert [(e["index"], e["session_name"]) for e in listed] == [(1, "a"), (2, "c")]
