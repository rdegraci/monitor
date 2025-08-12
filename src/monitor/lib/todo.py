import json
import logging
from typing import List, Dict, Any

from . import todo_redis as _todo_store

logger = logging.getLogger(__name__)

TODO_KEY_PREFIX = "todo:"
TODO_KEY_SUFFIX = ":coding_task"
TODO_TTL = 28800  # 8 hours, adjustable

def _session_id_from_key(key: str) -> str:
    """Extract the session_id from a key of the form f"{TODO_KEY_PREFIX}{session_id}{TODO_KEY_SUFFIX}"."""
    try:
        if not key.startswith(TODO_KEY_PREFIX):
            logger.warning(f"Key does not start with expected prefix: key={key}")
            return key
        if not key.endswith(TODO_KEY_SUFFIX):
            logger.warning(f"Key does not end with expected suffix: key={key}")
            return key[len(TODO_KEY_PREFIX):]
        start = len(TODO_KEY_PREFIX)
        end = len(key) - len(TODO_KEY_SUFFIX)
        return key[start:end]
    except Exception as e:
        logger.error(f"Error extracting session_id from key={key}: {e}")
        return key

def save_todo_to_memory(*, key: str, value: str, ttl: int) -> None:
    """
    Adapter: convert key/value usage to session_id-based API.
    """
    session_id = _session_id_from_key(key)
    todos: List[Dict[str, Any]] = []
    if value:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                todos = parsed
            else:
                logger.error(f"Invalid todos value for session_id={session_id}: not a list (type: {type(parsed)})")
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"JSON decode error in save_todo_to_memory for session_id={session_id}: {e}")
    _todo_store.save_todo_to_memory(session_id=session_id, todos=todos, ttl=ttl)

def read_todo_from_memory(key: str) -> str | None:
    """
    Adapter: read todos from session_id-based API and return as JSON string or None.
    """
    session_id = _session_id_from_key(key)
    todos = _todo_store.read_todo_from_memory(session_id=session_id)
    if not todos:
        return None
    try:
        return json.dumps(todos)
    except (TypeError, ValueError) as e:
        logger.error(f"JSON encode error in read_todo_from_memory for session_id={session_id}: {e}")
        return None

def clear_todo_from_memory(key: str) -> None:
    """
    Adapter: clear todos using session_id-based API.
    """
    session_id = _session_id_from_key(key)
    _todo_store.clear_todo_from_memory(session_id=session_id)

def _get_todo_key(session_id: str) -> str:
    """Generate the Redis key for the todo list based on session_id."""
    return f"{TODO_KEY_PREFIX}{session_id}{TODO_KEY_SUFFIX}"

def add_todo(session_id: str, item: str, priority: int = 0) -> str:
    """
    Add a new todo item to the list for the given session.
    
    :param session_id: The session identifier.
    :param item: The todo item description.
    :param priority: Optional priority (higher number = higher priority).
    :return: A JSON string indicating success and containing the action, session_id, item, priority, and the new count.
             Example: {"ok": true, "action": "add_todo", "session_id": "...", "item": "...", "priority": 1, "count": 3}
    """
    key = _get_todo_key(session_id)
    current_list = read_todo_from_memory(key)
    todos: List[Dict[str, Any]] = []
    if current_list:
        try:
            todos = json.loads(current_list)
            if not isinstance(todos, list):
                logger.error(f"Invalid todos data for session_id={session_id}: not a list (type: {type(todos)})")
                todos = []
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"JSON decode error reading todos for session_id={session_id}: {e}")
            todos = []
    todos.append({"item": item, "status": "pending", "priority": priority})
    # Optionally sort by priority if desired: todos.sort(key=lambda x: x['priority'], reverse=True)
    save_todo_to_memory(key=key, value=json.dumps(todos), ttl=TODO_TTL)
    logger.info(f"Added todo item for session_id={session_id}: item={item}, priority={priority}")
    print(f"Added todo item for session_id={session_id}: item={item}, priority={priority}")
    response = {
        "ok": True,
        "action": "add_todo",
        "session_id": session_id,
        "item": item,
        "priority": priority,
        "count": len(todos),
    }
    return json.dumps(response)

def list_todos(session_id: str) -> str:
    """
    Retrieve the current todo list for the given session as a JSON array string.
    
    :param session_id: The session identifier.
    :return: A JSON array string of todo items, each as {'item': str, 'status': str, 'priority': int}.
             Example: [{"item": "...", "status": "pending", "priority": 0}, ...]
    """
    key = _get_todo_key(session_id)
    current_list = read_todo_from_memory(key)
    todos: List[Dict[str, Any]] = []
    if current_list:
        try:
            todos = json.loads(current_list)
            if not isinstance(todos, list):
                logger.error(f"Invalid todos data for session_id={session_id}: not a list (type: {type(todos)})")
                todos = []
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"JSON decode error listing todos for session_id={session_id}: {e}")
            todos = []
    logger.info(f"Listed todos for session_id={session_id}: found {len(todos)} item(s)")
    print(f"Listed todos for session_id={session_id}: found {len(todos)} item(s)")
    return json.dumps(todos)

def update_todo(session_id: str, index: int, status: str = "done") -> str:
    """
    Update the status of a todo item at the given index for the session.
    
    :param session_id: The session identifier.
    :param index: The index of the todo item to update (0-based).
    :param status: The new status (e.g., 'done', 'in_progress').
    :return: A JSON string indicating success or failure.
             Success: {"ok": true, "action": "update_todo", "session_id": "...", "index": 0, "status": "...", "item": {...}}
             Failure (no list): {"ok": false, "action": "update_todo", "error": "not_found", "reason": "no todos for session", "session_id": "...", "index": 0, "status": "..."}
             Failure (index out of range): {"ok": false, "action": "update_todo", "error": "index_out_of_range", "session_id": "...", "index": 0, "count": <len>}
    """
    key = _get_todo_key(session_id)
    current_list = read_todo_from_memory(key)
    if not current_list:
        logger.info(f"Update failed for session_id={session_id}, index={index}, status={status}: no todos found")
        error_resp = {
            "ok": False,
            "action": "update_todo",
            "error": "not_found",
            "reason": "no todos for session",
            "session_id": session_id,
            "index": index,
            "status": status,
        }
        return json.dumps(error_resp)
    try:
        todos: List[Dict[str, Any]] = json.loads(current_list)
        if not isinstance(todos, list):
            logger.error(f"Invalid todos data for session_id={session_id}: not a list (type: {type(todos)})")
            error_resp = {
                "ok": False,
                "action": "update_todo",
                "error": "decode_error",
                "reason": "stored value is not a list",
                "session_id": session_id,
                "index": index,
                "status": status,
            }
            return json.dumps(error_resp)
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"JSON decode error updating todos for session_id={session_id}: {e}")
        error_resp = {
            "ok": False,
            "action": "update_todo",
            "error": "decode_error",
            "reason": "json_decode_error",
            "session_id": session_id,
            "index": index,
            "status": status,
        }
        return json.dumps(error_resp)
    if 0 <= index < len(todos):
        todos[index]["status"] = status
        save_todo_to_memory(key=key, value=json.dumps(todos), ttl=TODO_TTL)
        logger.info(f"Updated todo for session_id={session_id}, index={index}, status={status}: update succeeded")
        print(f"Updated todo for session_id={session_id}, index={index}, status={status}: update succeeded")
        resp = {
            "ok": True,
            "action": "update_todo",
            "session_id": session_id,
            "index": index,
            "status": status,
            "item": todos[index],
        }
        return json.dumps(resp)
    else:
        logger.warning(f"Update failed for session_id={session_id}, index={index}, status={status}: index out of range")
        error_resp = {
            "ok": False,
            "action": "update_todo",
            "error": "index_out_of_range",
            "session_id": session_id,
            "index": index,
            "count": len(todos),
        }
        return json.dumps(error_resp)

def clear_todos(session_id: str) -> str:
    """
    Clear the todo list for the given session by deleting the key.
    
    :param session_id: The session identifier.
    :return: A JSON string indicating success of the clear operation.
             Example: {"ok": true, "action": "clear_todos", "session_id": "..."}
    """
    key = _get_todo_key(session_id)
    clear_todo_from_memory(key)
    logger.info(f"Cleared todos for session_id={session_id}")
    print(f"Cleared todos for session_id={session_id}")
    response = {
        "ok": True,
        "action": "clear_todos",
        "session_id": session_id,
    }
    return json.dumps(response)
