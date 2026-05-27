import json
import logging
import uuid
from typing import Any, Dict, List

from . import todo_redis as _todo_store

logger = logging.getLogger(__name__)


def _resolve_session_id() -> str:
    """Resolve the todo session id from the harness session (the one shown in
    the system prompt as ``Session ID: ...``).

    Read lazily from ``monitor.config`` so there's no import cycle and we always
    pick up the current run's id. Falls back to ``"default"`` when the harness
    hasn't assigned one yet (e.g. when tools are exercised outside a configured
    run).
    """
    try:
        import monitor.config as config

        session_id = getattr(config, "SESSION_ID", None)
    except Exception:
        session_id = None
    return session_id or "default"


def _read_todos(session_id: str, *, context: str) -> List[Dict[str, Any]]:
    """Read the session's todos as a list, coercing malformed data to []."""
    value = _todo_store.read_todo_from_memory(session_id=session_id)
    if isinstance(value, list):
        return value
    if value:
        logger.error(
            "Invalid todos for %s: stored value is not a list (type=%s); resetting",
            context,
            type(value).__name__,
        )
    return []


def _new_id(existing_ids: set) -> str:
    """Generate a short stable id unique among ``existing_ids``."""
    while True:
        candidate = uuid.uuid4().hex[:8]
        if candidate not in existing_ids:
            return candidate


def _ensure_ids(todos: List[Dict[str, Any]]) -> bool:
    """Backfill ids for any item lacking one (migration / model-added items).

    Returns True if any item was mutated, so callers can persist.
    """
    changed = False
    existing = {
        t["id"] for t in todos if isinstance(t, dict) and t.get("id")
    }
    for entry in todos:
        if isinstance(entry, dict) and not entry.get("id"):
            new_id = _new_id(existing)
            entry["id"] = new_id
            existing.add(new_id)
            changed = True
    return changed


def _find_index(todos: List[Dict[str, Any]], todo_id: str) -> int:
    """Return the list index of the item with ``todo_id``, or -1."""
    for i, entry in enumerate(todos):
        if isinstance(entry, dict) and entry.get("id") == todo_id:
            return i
    return -1


def _priority_of(entry: Dict[str, Any]) -> int:
    """Best-effort integer priority for an item (defaults to 0)."""
    try:
        return int(entry.get("priority", 0))
    except (TypeError, ValueError):
        return 0


def add_todo(item: str, notes: str | None = None, priority: int = 0) -> str:
    """Add a new todo to the current session's plan and return its id.

    The session is taken from the harness session id, not a parameter.

    :param priority: Higher number sorts earlier in list_todos (default 0).
    :return: JSON ``{"ok", "action", "session_id", "id", "item", "priority", "count"}``.
             Items are stored as ``{"id", "item", "status", "priority", "notes"}``
             with status "pending".
    """
    session_id = _resolve_session_id()
    todos = _read_todos(session_id, context=f"add_todo session={session_id}")
    _ensure_ids(todos)
    existing = {t["id"] for t in todos if isinstance(t, dict) and t.get("id")}
    new_id = _new_id(existing)
    todos.append(
        {
            "id": new_id,
            "item": item,
            "status": "pending",
            "priority": priority,
            "notes": notes or "",
        }
    )
    _todo_store.save_todo_to_memory(session_id=session_id, todos=todos)
    logger.info(
        "add_todo session=%s id=%s item=%r priority=%s count=%d",
        session_id,
        new_id,
        item,
        priority,
        len(todos),
    )
    return json.dumps(
        {
            "ok": True,
            "action": "add_todo",
            "session_id": session_id,
            "id": new_id,
            "item": item,
            "priority": priority,
            "count": len(todos),
        }
    )


def list_todos() -> str:
    """Return the current session's plan as a JSON array, highest priority first.

    Ties keep insertion order (stable sort). Storage stays insertion-ordered;
    only this view is sorted, which is safe because items are addressed by id.

    :return: JSON array of ``{"id", "item", "status", "priority", "notes"}``.
             Use each item's ``id`` with update_todo / delete_todo.
    """
    session_id = _resolve_session_id()
    todos = _read_todos(session_id, context=f"list_todos session={session_id}")
    changed = _ensure_ids(todos)
    for entry in todos:
        if not isinstance(entry, dict):
            continue
        if "notes" not in entry:
            entry["notes"] = ""
            changed = True
        if "priority" not in entry:
            entry["priority"] = 0
            changed = True
    if changed:
        _todo_store.save_todo_to_memory(session_id=session_id, todos=todos)
    ordered = sorted(todos, key=lambda e: -_priority_of(e))
    logger.info("list_todos session=%s count=%d", session_id, len(ordered))
    return json.dumps(ordered)


def _read_for_mutation(session_id: str, action: str, **echo: Any):
    """Read todos for an id-addressed mutation.

    Returns ``(todos, None)`` on success, or ``(None, error_json)`` when there
    are no todos or the stored value is malformed.
    """
    value = _todo_store.read_todo_from_memory(session_id=session_id)
    if not value:
        logger.info("%s session=%s: no todos", action, session_id)
        return None, json.dumps(
            {
                "ok": False,
                "action": action,
                "error": "not_found",
                "reason": "no todos for session",
                "session_id": session_id,
                **echo,
            }
        )
    if not isinstance(value, list):
        logger.error("%s session=%s: stored value is not a list", action, session_id)
        return None, json.dumps(
            {
                "ok": False,
                "action": action,
                "error": "decode_error",
                "reason": "stored value is not a list",
                "session_id": session_id,
                **echo,
            }
        )
    return value, None


def update_todo(
    id: str,
    status: str | None = None,
    item: str | None = None,
    notes: str | None = None,
    priority: int | None = None,
) -> str:
    """Update a todo addressed by ``id``.

    Provide at least one of ``status`` (e.g. "in_progress", "done"), ``item``
    (new description), ``notes``, or ``priority``. Empty strings for item/notes
    are ignored; ``priority`` of 0 is honored.

    :return: JSON success ``{"ok": true, ..., "item": {...}}`` or an error
             envelope (``not_found`` / ``decode_error`` / ``id_not_found`` /
             ``nothing_to_update``).
    """
    session_id = _resolve_session_id()
    todos, error = _read_for_mutation(session_id, "update_todo", id=id)
    if error is not None:
        return error

    _ensure_ids(todos)
    index = _find_index(todos, id)
    if index == -1:
        logger.info("update_todo session=%s id=%s: not found", session_id, id)
        return json.dumps(
            {
                "ok": False,
                "action": "update_todo",
                "error": "id_not_found",
                "session_id": session_id,
                "id": id,
            }
        )

    if status is None and not item and not notes and priority is None:
        return json.dumps(
            {
                "ok": False,
                "action": "update_todo",
                "error": "nothing_to_update",
                "reason": "provide at least one of status, item, notes, priority",
                "session_id": session_id,
                "id": id,
            }
        )

    if status is not None:
        todos[index]["status"] = status
    if item:
        todos[index]["item"] = item
    if notes:
        todos[index]["notes"] = notes
    if priority is not None:
        todos[index]["priority"] = priority

    _todo_store.save_todo_to_memory(session_id=session_id, todos=todos)
    logger.info(
        "update_todo session=%s id=%s status=%s priority=%s",
        session_id,
        id,
        status,
        priority,
    )
    return json.dumps(
        {
            "ok": True,
            "action": "update_todo",
            "session_id": session_id,
            "id": id,
            "item": todos[index],
        }
    )


def delete_todo(id: str) -> str:
    """Remove a single todo addressed by ``id``.

    :return: JSON success ``{"ok": true, ..., "removed": {...}, "count": N}`` or
             an error envelope (``not_found`` / ``decode_error`` / ``id_not_found``).
    """
    session_id = _resolve_session_id()
    todos, error = _read_for_mutation(session_id, "delete_todo", id=id)
    if error is not None:
        return error

    _ensure_ids(todos)
    index = _find_index(todos, id)
    if index == -1:
        logger.info("delete_todo session=%s id=%s: not found", session_id, id)
        return json.dumps(
            {
                "ok": False,
                "action": "delete_todo",
                "error": "id_not_found",
                "session_id": session_id,
                "id": id,
            }
        )

    removed = todos.pop(index)
    _todo_store.save_todo_to_memory(session_id=session_id, todos=todos)
    logger.info(
        "delete_todo session=%s id=%s count=%d", session_id, id, len(todos)
    )
    return json.dumps(
        {
            "ok": True,
            "action": "delete_todo",
            "session_id": session_id,
            "id": id,
            "removed": removed,
            "count": len(todos),
        }
    )


def clear_todos() -> str:
    """Clear the current session's entire plan.

    :return: JSON ``{"ok", "action", "session_id"}``.
    """
    session_id = _resolve_session_id()
    _todo_store.clear_todo_from_memory(session_id=session_id)
    logger.info("clear_todos session=%s", session_id)
    return json.dumps(
        {
            "ok": True,
            "action": "clear_todos",
            "session_id": session_id,
        }
    )
