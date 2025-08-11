"""
Pytest unit tests for monitor.lib.todo
Covers: add_todo, list_todos, update_todo, clear_todos
Mocks the Redis utility functions imported inside todo.py.
"""

import json
import os
import sys
from typing import Dict

import pytest

# Ensure 'src' is on sys.path so `monitor` can be imported when running tests from repo root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from monitor.lib import todo  # noqa: E402  (import after sys.path tweak)


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

    monkeypatch.setattr(todo, "save_to_memory", fake_save_to_memory)
    monkeypatch.setattr(todo, "read_from_memory", fake_read_from_memory)
    monkeypatch.setattr(todo, "delete_from_memory", fake_delete_from_memory)

    return {"store": store, "ttls": ttls}


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
