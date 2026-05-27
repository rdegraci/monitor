"""Unit tests for monitor.lib.todo.

The todo tools are a per-session planning list the model works through over many
turns. Session comes from the harness (``monitor.config.SESSION_ID``), items
carry stable string ids, and update/delete address items by id. Tests drive the
in-memory fallback store with a pinned session id.
"""

import json

import pytest

import monitor.config as config
from monitor.lib import todo
from monitor.lib import todo_redis


SESSION = "session-test"


@pytest.fixture(autouse=True)
def fake_store(monkeypatch):
    """Force the in-memory fallback store and pin a known session id."""
    monkeypatch.setattr(todo_redis, "get_redis_client", lambda: None)
    todo_redis._TODO_MEMORY_STORE.clear()
    monkeypatch.setattr(config, "SESSION_ID", SESSION, raising=False)
    yield
    todo_redis._TODO_MEMORY_STORE.clear()


def _stored():
    return todo_redis.read_todo_from_memory(session_id=SESSION)


def _add(item, notes=None, priority=0):
    """Add and return the new id."""
    return json.loads(todo.add_todo(item, notes=notes, priority=priority))["id"]


# --- session resolution -----------------------------------------------------


def test_session_falls_back_to_default_when_unset(monkeypatch):
    monkeypatch.setattr(config, "SESSION_ID", None, raising=False)
    assert todo._resolve_session_id() == "default"


def test_session_uses_config_session_id():
    assert todo._resolve_session_id() == SESSION


# --- add_todo ---------------------------------------------------------------


def test_add_todo_returns_id_and_persists_item():
    resp = json.loads(todo.add_todo("Task A"))
    assert resp["ok"] is True
    assert resp["action"] == "add_todo"
    assert resp["count"] == 1
    new_id = resp["id"]
    assert isinstance(new_id, str) and new_id

    stored = _stored()
    assert stored == [
        {"id": new_id, "item": "Task A", "status": "pending", "priority": 0, "notes": ""}
    ]


def test_add_todo_ids_are_unique():
    id1 = _add("first")
    id2 = _add("second")
    assert id1 != id2
    assert [t["item"] for t in _stored()] == ["first", "second"]


def test_add_todo_with_notes():
    new_id = _add("Task A", notes="remember")
    item = next(t for t in _stored() if t["id"] == new_id)
    assert item["notes"] == "remember"


def test_add_todo_defaults_priority_zero_and_reports_it():
    resp = json.loads(todo.add_todo("Task A"))
    assert resp["priority"] == 0
    assert next(t for t in _stored() if t["id"] == resp["id"])["priority"] == 0


def test_add_todo_stores_given_priority():
    resp = json.loads(todo.add_todo("Task A", priority=5))
    assert resp["priority"] == 5
    assert next(t for t in _stored() if t["id"] == resp["id"])["priority"] == 5


# --- list_todos -------------------------------------------------------------


def test_list_todos_empty():
    assert json.loads(todo.list_todos()) == []


def test_list_todos_returns_items_with_ids():
    new_id = _add("Task A", notes="n")
    data = json.loads(todo.list_todos())
    assert data == [
        {"id": new_id, "item": "Task A", "status": "pending", "priority": 0, "notes": "n"}
    ]


def test_list_todos_sorts_by_priority_desc_stable():
    a = _add("low-1", )            # priority 0
    b = json.loads(todo.add_todo("high", priority=10))["id"]
    c = _add("low-2")             # priority 0
    d = json.loads(todo.add_todo("mid", priority=5))["id"]

    order = [t["id"] for t in json.loads(todo.list_todos())]
    # high(10), mid(5), then the two priority-0 items in insertion order.
    assert order == [b, d, a, c]


def test_list_todos_backfills_priority_for_legacy_items():
    todo_redis.save_todo_to_memory(
        session_id=SESSION,
        todos=[{"item": "Legacy", "status": "pending"}],
    )
    data = json.loads(todo.list_todos())
    assert data[0]["priority"] == 0
    # backfill persisted
    assert _stored()[0]["priority"] == 0


def test_list_todos_backfills_ids_and_notes_for_legacy_items():
    # Legacy data: no ids, one missing notes.
    todo_redis.save_todo_to_memory(
        session_id=SESSION,
        todos=[
            {"item": "Legacy A", "status": "pending"},
            {"item": "Legacy B", "status": "done", "notes": "kept"},
        ],
    )
    data = json.loads(todo.list_todos())
    assert all(t["id"] for t in data)
    assert len({t["id"] for t in data}) == 2  # unique
    assert data[0]["notes"] == ""
    assert data[1]["notes"] == "kept"
    # Backfill was persisted.
    assert all(t["id"] for t in _stored())


def test_list_todos_non_list_returns_empty():
    todo_redis.save_todo_to_memory(session_id=SESSION, todos={"unexpected": "x"})
    assert json.loads(todo.list_todos()) == []


# --- update_todo ------------------------------------------------------------


def test_update_todo_not_found_when_empty():
    resp = json.loads(todo.update_todo(id="whatever", status="done"))
    assert resp["ok"] is False
    assert resp["error"] == "not_found"


def test_update_todo_id_not_found():
    _add("Task A")
    resp = json.loads(todo.update_todo(id="nope", status="done"))
    assert resp["ok"] is False
    assert resp["error"] == "id_not_found"


def test_update_todo_changes_status_by_id():
    new_id = _add("Task A")
    resp = json.loads(todo.update_todo(id=new_id, status="done"))
    assert resp["ok"] is True
    assert resp["item"]["status"] == "done"
    assert next(t for t in _stored() if t["id"] == new_id)["status"] == "done"


def test_update_todo_edits_item_text():
    new_id = _add("old text")
    todo.update_todo(id=new_id, item="new text")
    assert next(t for t in _stored() if t["id"] == new_id)["item"] == "new text"


def test_update_todo_requires_a_field():
    new_id = _add("Task A")
    resp = json.loads(todo.update_todo(id=new_id))
    assert resp["ok"] is False
    assert resp["error"] == "nothing_to_update"


def test_update_todo_changes_priority_including_zero():
    new_id = _add("Task A", priority=5)
    todo.update_todo(id=new_id, priority=9)
    assert next(t for t in _stored() if t["id"] == new_id)["priority"] == 9
    # Setting priority back to 0 must be honored (0 is not "no value").
    resp = json.loads(todo.update_todo(id=new_id, priority=0))
    assert resp["ok"] is True
    assert next(t for t in _stored() if t["id"] == new_id)["priority"] == 0


def test_update_todo_ignores_empty_item_and_notes():
    new_id = _add("Task A", notes="orig")
    todo.update_todo(id=new_id, status="done", item="", notes="")
    item = next(t for t in _stored() if t["id"] == new_id)
    assert item["status"] == "done"
    assert item["item"] == "Task A"
    assert item["notes"] == "orig"


def test_update_todo_non_list_returns_decode_error():
    todo_redis.save_todo_to_memory(session_id=SESSION, todos={"not": "a list"})
    resp = json.loads(todo.update_todo(id="x", status="done"))
    assert resp["ok"] is False
    assert resp["error"] == "decode_error"


# --- delete_todo ------------------------------------------------------------


def test_delete_todo_removes_one_keeps_others():
    id1 = _add("first")
    id2 = _add("second")
    resp = json.loads(todo.delete_todo(id=id1))
    assert resp["ok"] is True
    assert resp["removed"]["id"] == id1
    assert resp["count"] == 1
    remaining = [t["id"] for t in _stored()]
    assert remaining == [id2]


def test_delete_todo_id_not_found():
    _add("first")
    resp = json.loads(todo.delete_todo(id="nope"))
    assert resp["ok"] is False
    assert resp["error"] == "id_not_found"
    assert len(_stored()) == 1


def test_delete_todo_not_found_when_empty():
    resp = json.loads(todo.delete_todo(id="x"))
    assert resp["ok"] is False
    assert resp["error"] == "not_found"


def test_ids_stable_across_delete():
    """Deleting one item does not change the surviving item's id."""
    id1 = _add("first")
    id2 = _add("second")
    id3 = _add("third")
    todo.delete_todo(id=id2)
    # id1 and id3 must still address the same items.
    assert json.loads(todo.update_todo(id=id3, status="done"))["ok"] is True
    assert next(t for t in _stored() if t["id"] == id3)["item"] == "third"
    assert next(t for t in _stored() if t["id"] == id1)["item"] == "first"


# --- clear_todos ------------------------------------------------------------


def test_clear_todos_empties_plan():
    _add("Task A")
    resp = json.loads(todo.clear_todos())
    assert resp == {"ok": True, "action": "clear_todos", "session_id": SESSION}
    assert _stored() == []


# --- store fallback ---------------------------------------------------------


def test_fallback_isolated_per_session():
    todo_redis.save_todo_to_memory(session_id="s1", todos=[{"item": "one"}])
    todo_redis.save_todo_to_memory(session_id="s2", todos=[{"item": "two"}])
    assert todo_redis.read_todo_from_memory(session_id="s1") == [{"item": "one"}]
    assert todo_redis.read_todo_from_memory(session_id="s2") == [{"item": "two"}]
    todo_redis.clear_todo_from_memory(session_id="s1")
    assert todo_redis.read_todo_from_memory(session_id="s1") == []
    assert todo_redis.read_todo_from_memory(session_id="s2") == [{"item": "two"}]
