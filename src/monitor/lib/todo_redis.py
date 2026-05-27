import logging
import json
from threading import Lock
from typing import List, Dict
from .redis_utils import get_redis_client

logger = logging.getLogger(__name__)

TODO_KEY_FORMAT = "todo:{session_id}:coding_task"
TODO_TTL = 28800  # 8 hours — single source of truth for todo expiry
_TODO_MEMORY_STORE = {}
_TODO_MEMORY_LOCK = Lock()


def save_todo_to_memory(session_id: str, todos: List[Dict], ttl: int = TODO_TTL):
    """
    Save the todo list for a session directly to Redis as a JSON-encoded array.
    """
    key = TODO_KEY_FORMAT.format(session_id=session_id)
    client = get_redis_client()
    if client is None:
        logger.info("Redis unavailable; using in-memory todo fallback for session_id=%s", session_id)
        with _TODO_MEMORY_LOCK:
            _TODO_MEMORY_STORE[key] = json.dumps(todos)
        return
    try:
        payload = json.dumps(todos)
    except Exception as e:
        logger.error("Failed to serialize todos for session_id=%s: %s", session_id, e)
        return
    client.setex(key, ttl, payload)


def read_todo_from_memory(session_id: str) -> List[Dict]:
    """
    Read the todo list for a session from Redis. Returns a list of todos (may be empty).
    """
    key = TODO_KEY_FORMAT.format(session_id=session_id)
    client = get_redis_client()
    if client is None:
        logger.info("Redis unavailable; reading in-memory todo fallback for session_id=%s", session_id)
        with _TODO_MEMORY_LOCK:
            data = _TODO_MEMORY_STORE.get(key)
        if not data:
            return []
        try:
            return json.loads(data)
        except Exception as e:
            logger.error(
                "Malformed in-memory todo data for session_id=%s: %s", session_id, e
            )
            return []
    data = client.get(key)
    if not data:
        return []
    try:
        return json.loads(data)
    except Exception as e:
        logger.error(
            "Malformed todo data for session_id=%s: %s", session_id, e
        )
        # Recovery: bad data -> reset to empty
        return []


def clear_todo_from_memory(session_id: str):
    """
    Remove the todo list for a session from Redis.
    """
    key = TODO_KEY_FORMAT.format(session_id=session_id)
    client = get_redis_client()
    if client is None:
        logger.info("Redis unavailable; clearing in-memory todo fallback for session_id=%s", session_id)
        with _TODO_MEMORY_LOCK:
            _TODO_MEMORY_STORE.pop(key, None)
        return
    client.delete(key)
