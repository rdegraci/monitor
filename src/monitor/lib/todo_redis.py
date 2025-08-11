import json
from typing import List, Dict
from .redis_utils import get_redis_client

TODO_KEY_FORMAT = "todo:{session_id}:coding_task"
TODO_TTL = 1800  # 30 minutes (default)

def save_todo_to_memory(session_id: str, todos: List[Dict], ttl: int = TODO_TTL):
    """
    Save the todo list for a session directly to Redis as a JSON-encoded array.
    """
    key = TODO_KEY_FORMAT.format(session_id=session_id)
    client = get_redis_client()
    client.setex(key, ttl, json.dumps(todos))

def read_todo_from_memory(session_id: str) -> List[Dict]:
    """
    Read the todo list for a session from Redis. Returns a list of todos (may be empty).
    """
    key = TODO_KEY_FORMAT.format(session_id=session_id)
    client = get_redis_client()
    data = client.get(key)
    if not data:
        return []
    try:
        return json.loads(data)
    except Exception:
        # Recovery: bad data -> reset to empty
        return []

def clear_todo_from_memory(session_id: str):
    """
    Remove the todo list for a session from Redis.
    """
    key = TODO_KEY_FORMAT.format(session_id=session_id)
    client = get_redis_client()
    client.delete(key)
