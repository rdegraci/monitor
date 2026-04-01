"""
Pytest unit tests for monitor.lib.todo
Covers: add_todo, list_todos, update_todo, clear_todos
Mocks the Redis utility functions imported inside todo.py.
Extended to cover handling when stored values are invalid JSON or not a list.
"""

import json
import os
import sys
from typing import Dict

import pytest

# Ensure 'src' is on sys.path so `monitor` can be imported when running tests from repo root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from monitor.lib import todo  # noqa: E402  (import after sys.path tweak)
from monitor.lib import todo_redis  # noqa: E402  (import after sys.path tweak)


@pytest.fixture()
def fake_memory(monkeypatch) -> Dict[str, str]:
    """Provide a simple in-memory stand-in for Redis functions used by todo.py.

    The store maps key -> value (JSON string). A separate dict tracks TTL per key.
    """
    store: Dict[str, str] = {}
    ttls: Dict[str, int] = {}

    def fake_save_to_memory(*, key: str, value: str, ttl: int) -> None:
        store[key] = value
        ttls[key] = ttl

    def fake_read_from_memory(key: str) -> str:
        return store.get(key)

    def fake_delete_from_memory(key: str) -> None:
        store.pop(key, None)
        ttls.pop(key, None)

    monkeypatch.setattr(todo, "save_todo_to_memory", fake_save_to_memory)
    monkeypatch.setattr(todo, "read_todo_from_memory", fake_read_from_memory)
    monkeypatch.setattr(todo, "clear_todo_from_memory", fake_delete_from_memory)

    return {"store": store, "ttls": ttls}


@pytest.fixture()
def fallback_memory(monkeypatch):
    monkeypatch.setattr(todo_redis, "get_redis_client", lambda: None)
    if hasattr(todo_redis, "_IN_MEMORY_TODO_STORE"):
        todo_redis._IN_MEMORY_TODO_STORE.clear()
    return todo_redis


def _key(session_id: str) -> str:
    return f"todo:{session_id}:coding_task"


def test_list_todos_empty_when_none(fake_memory):
    session_id = "session-123"
    # No preloaded data -> read_from_memory returns None
    result = todo.list_todos(session_id)
    assert isinstance(result, str)
    data = json.loads(result)
    assert data == []


def test_add_todo_adds_item_and_returns_ok(fake_memory):
    session_id = "session-123"
    result = todo.add_todo(session_id, "Task A", priority=1)

    # Verify response JSON
    resp = json.loads(result)
    assert resp["ok"] is True
    assert resp["action"] == "add_todo"
    assert resp["session_id"] == session_id
    assert resp["item"] == "Task A"
    assert resp["priority"] == 1
    assert resp["count"] == 1

    # Verify stored data
    store = fake_memory["store"]
    ttls = fake_memory["ttls"]
    key = _key(session_id)
    assert key in store
    saved_list = json.loads(store[key])
    assert isinstance(saved_list, list) and len(saved_list) == 1
    assert saved_list[0]["item"] == "Task A"
    assert saved_list[0]["status"] == "pending"
    assert saved_list[0]["priority"] == 1

    # TTL recorded
    assert key in ttls
    assert isinstance(ttls[key], int) and ttls[key] > 0
    # Prefer exact TTL match if constants are stable
    assert ttls[key] == todo.TODO_TTL


def test_update_todo_not_found_when_none(fake_memory):
    session_id = "session-123"
    result = todo.update_todo(session_id, index=0, status="done")
    resp = json.loads(result)
    assert resp["ok"] is False
    assert resp["action"] == "update_todo"
    assert resp["error"] == "not_found"
    assert resp["reason"] == "no todos for session"
    assert resp["session_id"] == session_id
    assert resp["index"] == 0
    assert resp["status"] == "done"


def test_update_todo_updates_status(fake_memory):
    session_id = "session-123"
    # Preload one pending item
    key = _key(session_id)
    fake_memory["store"][key] = json.dumps([
        {"item": "Task A", "status": "pending", "priority": 0}
    ])

    result = todo.update_todo(session_id, index=0, status="done")
    resp = json.loads(result)
    assert resp["ok"] is True
    assert resp["action"] == "update_todo"
    assert resp["session_id"] == session_id
    assert resp["index"] == 0
    assert resp["status"] == "done"
    assert resp["item"]["item"] == "Task A"
    assert resp["item"]["status"] == "done"

    # Verify store is updated and TTL set
    saved_list = json.loads(fake_memory["store"][key])
    assert saved_list[0]["status"] == "done"
    assert fake_memory["ttls"][key] == todo.TODO_TTL


def test_update_todo_index_out_of_range(fake_memory):
    session_id = "session-123"
    key = _key(session_id)
    fake_memory["store"][key] = json.dumps([
        {"item": "Only Task", "status": "pending", "priority": 0}
    ])

    result = todo.update_todo(session_id, index=5, status="in_progress")
    resp = json.loads(result)
    assert resp["ok"] is False
    assert resp["action"] == "update_todo"
    assert resp["error"] == "index_out_of_range"
    assert resp["session_id"] == session_id
    assert resp["index"] == 5
    assert resp["count"] == 1


def test_clear_todos_deletes_key(fake_memory):
    session_id = "session-123"
    key = _key(session_id)
    fake_memory["store"][key] = json.dumps([
        {"item": "Task to clear", "status": "pending", "priority": 0}
    ])

    result = todo.clear_todos(session_id)
    resp = json.loads(result)
    assert resp["ok"] is True
    assert resp["action"] == "clear_todos"
    assert resp["session_id"] == session_id

    # Ensure key removed
    assert key not in fake_memory["store"]
    assert key not in fake_memory["ttls"]


def test_list_todos_invalid_json_returns_empty_list(fake_memory):
    session_id = "session-123"
    key = _key(session_id)
    # Preload invalid JSON string
    fake_memory["store"][key] = "{this is not valid json"

    result = todo.list_todos(session_id)
    assert isinstance(result, str)
    data = json.loads(result)
    assert data == []


def test_list_todos_non_list_returns_empty_list(fake_memory):
    session_id = "session-123"
    key = _key(session_id)
    # Preload valid JSON but not a list
    fake_memory["store"][key] = json.dumps({"unexpected": "mapping"})

    result = todo.list_todos(session_id)
    assert isinstance(result, str)
    data = json.loads(result)
    assert data == []


def test_add_todo_recovers_from_invalid_json(fake_memory):
    session_id = "session-123"
    key = _key(session_id)
    # Preload invalid JSON string
    fake_memory["store"][key] = "not-json!!"

    result = todo.add_todo(session_id, "Recovered Task", priority=2)
    resp = json.loads(result)
    assert resp["ok"] is True
    assert resp["action"] == "add_todo"
    assert resp["session_id"] == session_id
    assert resp["item"] == "Recovered Task"
    assert resp["priority"] == 2
    assert resp["count"] == 1

    # Verify saved list has only the new item
    saved_list = json.loads(fake_memory["store"][key])
    assert isinstance(saved_list, list)
    assert len(saved_list) == 1
    assert saved_list[0]["item"] == "Recovered Task"
    assert saved_list[0]["status"] == "pending"
    assert saved_list[0]["priority"] == 2

    # TTL recorded
    assert fake_memory["ttls"][key] == todo.TODO_TTL


def test_add_todo_recovers_from_non_list_value(fake_memory):
    session_id = "session-123"
    key = _key(session_id)
    # Preload valid JSON but not a list
    fake_memory["store"][key] = json.dumps({"oops": True})

    result = todo.add_todo(session_id, "Recovered From Non-List", priority=3)
    resp = json.loads(result)
    assert resp["ok"] is True
    assert resp["action"] == "add_todo"
    assert resp["session_id"] == session_id
    assert resp["item"] == "Recovered From Non-List"
    assert resp["priority"] == 3
    assert resp["count"] == 1

    # Verify saved list has only the new item
    saved_list = json.loads(fake_memory["store"][key])
    assert isinstance(saved_list, list)
    assert len(saved_list) == 1
    assert saved_list[0]["item"] == "Recovered From Non-List"
    assert saved_list[0]["status"] == "pending"
    assert saved_list[0]["priority"] == 3

    # TTL recorded
    assert fake_memory["ttls"][key] == todo.TODO_TTL


def test_update_todo_invalid_json_returns_decode_error(fake_memory):
    session_id = "session-123"
    key = _key(session_id)
    # Preload invalid JSON string
    fake_memory["store"][key] = "}{ invalid json ]["
    result = todo.update_todo(session_id, index=0, status="done")
    resp = json.loads(result)
    assert resp["ok"] is False
    assert resp["action"] == "update_todo"
    assert resp["error"] == "decode_error"
    assert resp["session_id"] == session_id
    assert resp["index"] == 0
    assert resp["status"] == "done"


def test_update_todo_non_list_returns_decode_error(fake_memory):
    session_id = "session-123"
    key = _key(session_id)
    # Preload valid JSON but not a list
    fake_memory["store"][key] = json.dumps({"not": "a list"})
    result = todo.update_todo(session_id, index=0, status="done")
    resp = json.loads(result)
    assert resp["ok"] is False
    assert resp["action"] == "update_todo"
    assert resp["error"] == "decode_error"
    assert resp["session_id"] == session_id
    assert resp["index"] == 0
    assert resp["status"] == "done"


def test_add_todo_sets_empty_notes_when_not_provided(fake_memory):
    session_id = "session-notes-1"
    key = _key(session_id)
    result = todo.add_todo(session_id, "Notes Default Empty", priority=0)
    resp = json.loads(result)
    assert resp["ok"] is True
    saved_list = json.loads(fake_memory["store"][key])
    assert isinstance(saved_list, list) and len(saved_list) == 1
    assert saved_list[0]["item"] == "Notes Default Empty"
    assert saved_list[0]["notes"] == ""
    assert fake_memory["ttls"][key] == todo.TODO_TTL


def test_add_todo_with_notes_persists_notes(fake_memory):
    session_id = "session-notes-2"
    key = _key(session_id)
    result = todo.add_todo(session_id, "Notes Provided", priority=1, notes="remember to test notes")
    resp = json.loads(result)
    assert resp["ok"] is True
    saved_list = json.loads(fake_memory["store"][key])
    assert isinstance(saved_list, list) and len(saved_list) == 1
    assert saved_list[0]["item"] == "Notes Provided"
    assert saved_list[0]["notes"] == "remember to test notes"
    assert fake_memory["ttls"][key] == todo.TODO_TTL


def test_list_todos_backfills_missing_notes_on_legacy_items(fake_memory):
    session_id = "session-notes-3"
    key = _key(session_id)
    fake_memory["store"][key] = json.dumps([
        {"item": "Legacy Missing Notes", "status": "pending", "priority": 0},
        {"item": "Already Has Notes", "status": "done", "priority": 1, "notes": "kept"}
    ])
    result = todo.list_todos(session_id)
    assert isinstance(result, str)
    data = json.loads(result)
    assert isinstance(data, list) and len(data) == 2
    assert data[0]["item"] == "Legacy Missing Notes"
    assert data[0]["notes"] == ""
    assert data[1]["item"] == "Already Has Notes"
    assert data[1]["notes"] == "kept"


def test_update_todo_does_not_overwrite_notes_when_notes_none(fake_memory):
    session_id = "session-notes-4"
    key = _key(session_id)
    fake_memory["store"][key] = json.dumps([
        {"item": "Task With Notes", "status": "pending", "priority": 0, "notes": "original notes"}
    ])
    result = todo.update_todo(session_id, index=0, status="in_progress")
    resp = json.loads(result)
    assert resp["ok"] is True
    assert resp["item"]["notes"] == "original notes"
    saved_list = json.loads(fake_memory["store"][key])
    assert saved_list[0]["notes"] == "original notes"
    assert fake_memory["ttls"][key] == todo.TODO_TTL


def test_update_todo_does_not_overwrite_notes_when_empty_string(fake_memory):
    session_id = "session-notes-5"
    key = _key(session_id)
    fake_memory["store"][key] = json.dumps([
        {"item": "Task Keep Notes", "status": "pending", "priority": 0, "notes": "keep me"}
    ])
    result = todo.update_todo(session_id, index=0, status="done", notes="")
    resp = json.loads(result)
    assert resp["ok"] is True
    assert resp["item"]["notes"] == "keep me"
    saved_list = json.loads(fake_memory["store"][key])
    assert saved_list[0]["notes"] == "keep me"
    assert fake_memory["ttls"][key] == todo.TODO_TTL


def test_update_todo_updates_notes_when_non_empty(fake_memory):
    session_id = "session-notes-6"
    key = _key(session_id)
    fake_memory["store"][key] = json.dumps([
        {"item": "Task Update Notes", "status": "pending", "priority": 0, "notes": "old"}
    ])
    result = todo.update_todo(session_id, index=0, status="done", notes="new note value")
    resp = json.loads(result)
    assert resp["ok"] is True
    assert resp["item"]["notes"] == "new note value"
    saved_list = json.loads(fake_memory["store"][key])
    assert saved_list[0]["notes"] == "new note value"
    assert fake_memory["ttls"][key] == todo.TODO_TTL


def test_update_todo_updates_notes_for_legacy_item_without_notes(fake_memory):
    session_id = "session-notes-7"
    key = _key(session_id)
    fake_memory["store"][key] = json.dumps([
        {"item": "Legacy No Notes", "status": "pending", "priority": 0}
    ])
    result = todo.update_todo(session_id, index=0, status="done", notes="added later")
    resp = json.loads(result)
    assert resp["ok"] is True
    assert resp["item"]["notes"] == "added later"
    saved_list = json.loads(fake_memory["store"][key])
    assert saved_list[0].get("notes") == "added later"
    assert fake_memory["ttls"][key] == todo.TODO_TTL


def test_todo_redis_fallback_persists_data_for_same_session(fallback_memory):
    session_id = "fallback-session-1"

    fallback_memory.save_todo_to_memory(session_id=session_id, todos=[{"item": "Task A"}])
    assert fallback_memory.read_todo_from_memory(session_id) == [{"item": "Task A"}]

    fallback_memory.save_todo_to_memory(session_id=session_id, todos=[{"item": "Task A"}, {"item": "Task B"}])
    assert fallback_memory.read_todo_from_memory(session_id) == [{"item": "Task A"}, {"item": "Task B"}]

    fallback_memory.clear_todo_from_memory(session_id)
    assert fallback_memory.read_todo_from_memory(session_id) == []


def test_todo_redis_fallback_isolated_per_session(fallback_memory):
    session_id_1 = "fallback-session-1"
    session_id_2 = "fallback-session-2"

    fallback_memory.save_todo_to_memory(session_id=session_id_1, todos=[{"item": "Task One"}])
    fallback_memory.save_todo_to_memory(session_id=session_id_2, todos=[{"item": "Task Two"}])

    assert fallback_memory.read_todo_from_memory(session_id_1) == [{"item": "Task One"}]
    assert fallback_memory.read_todo_from_memory(session_id_2) == [{"item": "Task Two"}]

    fallback_memory.clear_todo_from_memory(session_id_1)

    assert fallback_memory.read_todo_from_memory(session_id_1) == []
    assert fallback_memory.read_todo_from_memory(session_id_2) == [{"item": "Task Two"}]
