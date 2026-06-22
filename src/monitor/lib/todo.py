import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from monitor.lib.colors import blue, reset

from . import todo_redis as _todo_store

logger = logging.getLogger(__name__)
_MAX_SCOPE_CHANGES = 12


def _print_todo_action(symbol: str, message: str) -> None:
    """Print one-line terminal feedback for an LLM-triggered todo action.

    The model's tool result still comes back as the JSON envelope; this is a
    side-channel echo to the user's terminal so they can see the plan being
    built/edited as the model works.
    """
    print(f"{blue}[task {symbol}]{reset} {message}")


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


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_task_context() -> Dict[str, Any]:
    return {
        "acceptance_criteria": [],
        "scope_changes": [],
        "checkpoint": None,
    }


def _read_task_context(session_id: str) -> Dict[str, Any]:
    value = _todo_store.read_task_context_from_memory(session_id=session_id)
    if not isinstance(value, dict):
        return _default_task_context()
    context = _default_task_context()
    acceptance = value.get("acceptance_criteria")
    if isinstance(acceptance, list):
        context["acceptance_criteria"] = [
            str(item).strip() for item in acceptance if str(item).strip()
        ]
    scope_changes = value.get("scope_changes")
    if isinstance(scope_changes, list):
        context["scope_changes"] = [
            entry for entry in scope_changes if isinstance(entry, dict)
        ][-_MAX_SCOPE_CHANGES:]
    checkpoint = value.get("checkpoint")
    if isinstance(checkpoint, dict):
        context["checkpoint"] = checkpoint
    return context


def _save_task_context(session_id: str, context: Dict[str, Any]) -> None:
    _todo_store.save_task_context_to_memory(session_id=session_id, context=context)


def _append_scope_change(
    context: Dict[str, Any], summary: str, *, material: bool
) -> Dict[str, Any]:
    entry = {
        "summary": str(summary).strip(),
        "material": bool(material),
        "created_at": _now_utc_iso(),
    }
    scope_changes = list(context.get("scope_changes") or [])
    scope_changes.append(entry)
    context["scope_changes"] = scope_changes[-_MAX_SCOPE_CHANGES:]
    return entry


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
    _print_todo_action("+", f"{new_id} P{priority} {item}")
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


def add_discovered_work(
    item: str,
    notes: str | None = None,
    priority: int = 0,
    material: bool = False,
    scope_summary: str | None = None,
) -> str:
    """Add newly discovered work to the plan, optionally recording scope growth.

    This is the preferred tool when the orchestrator uncovers new required work
    mid-task: it creates the todo and, when relevant, records that scope grew.
    Exact duplicate items are reused instead of duplicated.
    """
    session_id = _resolve_session_id()
    item_text = str(item).strip()
    if not item_text:
        return json.dumps(
            {
                "ok": False,
                "action": "add_discovered_work",
                "error": "empty_item",
                "reason": "item must be a non-empty string",
                "session_id": session_id,
            }
        )

    todos = _read_todos(session_id, context=f"add_discovered_work session={session_id}")
    _ensure_ids(todos)
    context = _read_task_context(session_id)

    existing = next(
        (
            entry for entry in todos
            if isinstance(entry, dict)
            and str(entry.get("item", "")).strip() == item_text
        ),
        None,
    )
    created = False
    if existing is None:
        existing_ids = {t["id"] for t in todos if isinstance(t, dict) and t.get("id")}
        todo_entry = {
            "id": _new_id(existing_ids),
            "item": item_text,
            "status": "pending",
            "priority": priority,
            "notes": notes or "",
        }
        todos.append(todo_entry)
        existing = todo_entry
        created = True
        _todo_store.save_todo_to_memory(session_id=session_id, todos=todos)
        logger.info(
            "add_discovered_work session=%s id=%s item=%r priority=%s created=true",
            session_id,
            todo_entry["id"],
            item_text,
            priority,
        )
        _print_todo_action("+", f"{todo_entry['id']} P{priority} discovered {item_text}")
    else:
        logger.info(
            "add_discovered_work session=%s id=%s item=%r reused=true",
            session_id,
            existing.get("id"),
            item_text,
        )
        _print_todo_action("~", f"{existing.get('id')} discovered work already tracked")

    scope_change = None
    if material or scope_summary:
        scope_text = str(scope_summary or item_text).strip()
        if scope_text:
            scope_change = _append_scope_change(context, scope_text, material=material)
            _save_task_context(session_id, context)
            logger.info(
                "add_discovered_work session=%s recorded_scope material=%s summary=%r",
                session_id,
                material,
                scope_text,
            )
            _print_todo_action(
                "!",
                f"scope {'material' if material else 'minor'} {scope_change['summary']}",
            )

    return json.dumps(
        {
            "ok": True,
            "action": "add_discovered_work",
            "session_id": session_id,
            "created": created,
            "todo": existing,
            "scope_change": scope_change,
            "count": len(todos),
        }
    )


def get_task_context() -> str:
    """Return session-scoped task context for resume/recovery decisions."""
    session_id = _resolve_session_id()
    context = _read_task_context(session_id)
    logger.info("get_task_context session=%s", session_id)
    _print_todo_action(
        "?",
        (
            f"context criteria={len(context['acceptance_criteria'])} "
            f"scope_changes={len(context['scope_changes'])} "
            f"checkpoint={'yes' if context['checkpoint'] else 'no'}"
        ),
    )
    return json.dumps(context)


def set_task_acceptance(criteria: List[str]) -> str:
    """Replace the session's acceptance criteria list."""
    session_id = _resolve_session_id()
    context = _read_task_context(session_id)
    ordered: List[str] = []
    seen = set()
    for item in criteria or []:
        text = str(item).strip()
        if not text or text in seen:
            continue
        ordered.append(text)
        seen.add(text)
    context["acceptance_criteria"] = ordered
    _save_task_context(session_id, context)
    logger.info("set_task_acceptance session=%s count=%d", session_id, len(ordered))
    _print_todo_action("*", f"acceptance criteria {len(ordered)} item{'s' if len(ordered) != 1 else ''}")
    return json.dumps(
        {
            "ok": True,
            "action": "set_task_acceptance",
            "session_id": session_id,
            "acceptance_criteria": ordered,
            "count": len(ordered),
        }
    )


def save_task_checkpoint(summary: str, next_step: str, blockers: str | None = None) -> str:
    """Persist a lightweight resume checkpoint for the current session."""
    session_id = _resolve_session_id()
    context = _read_task_context(session_id)
    checkpoint = {
        "summary": str(summary).strip(),
        "next_step": str(next_step).strip(),
        "blockers": str(blockers or "").strip(),
        "updated_at": _now_utc_iso(),
    }
    context["checkpoint"] = checkpoint
    _save_task_context(session_id, context)
    logger.info("save_task_checkpoint session=%s next_step=%r", session_id, checkpoint["next_step"])
    _print_todo_action(">", f"checkpoint next: {checkpoint['next_step'] or checkpoint['summary']}")
    return json.dumps(
        {
            "ok": True,
            "action": "save_task_checkpoint",
            "session_id": session_id,
            "checkpoint": checkpoint,
        }
    )


def record_task_scope_change(summary: str, material: bool = True) -> str:
    """Append a scope-growth note for the current session."""
    session_id = _resolve_session_id()
    context = _read_task_context(session_id)
    entry = _append_scope_change(context, summary, material=material)
    _save_task_context(session_id, context)
    logger.info(
        "record_task_scope_change session=%s material=%s summary=%r",
        session_id,
        entry["material"],
        entry["summary"],
    )
    _print_todo_action("!", f"scope {'material' if entry['material'] else 'minor'} {entry['summary']}")
    return json.dumps(
        {
            "ok": True,
            "action": "record_task_scope_change",
            "session_id": session_id,
            "scope_change": entry,
            "count": len(context["scope_changes"]),
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
    _print_todo_action("=", f"listed {len(ordered)} item{'s' if len(ordered) != 1 else ''}")
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

    # Capture pre-mutation values so the terminal echo can show what actually
    # changed (e.g. "status: pending -> done") rather than just what was set.
    before = dict(todos[index])

    # Compute the diff up-front so a no-op update fails fast — no mutation,
    # no persistence, and the model gets a clear signal that it's spinning
    # on update_todo without actually advancing the work.
    changes = []
    if status is not None and before.get("status") != status:
        changes.append(f"status: {before.get('status')} -> {status}")
    if item and before.get("item") != item:
        changes.append(f"item: {item!r}")
    if notes and before.get("notes") != notes:
        changes.append(f"notes: {notes!r}")
    if priority is not None and before.get("priority") != priority:
        changes.append(f"priority: {before.get('priority')} -> {priority}")

    if not changes:
        logger.info("update_todo session=%s id=%s: no-op (no fields changed)", session_id, id)
        _print_todo_action("~", f"{id} (no-op rejected)")
        return json.dumps(
            {
                "ok": False,
                "action": "update_todo",
                "error": "no_effective_change",
                "reason": (
                    "All provided fields already match current values. "
                    "Either change at least one field or move on — don't retry "
                    "the same update_todo."
                ),
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
    detail = "; ".join(changes)
    _print_todo_action("~", f"{id} {detail}")
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
    _print_todo_action("-", f"{id} {removed.get('item', '')}")
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
    # Read first so we can report the count being cleared.
    existing = _todo_store.read_todo_from_memory(session_id=session_id) or []
    count = len(existing) if isinstance(existing, list) else 0
    _todo_store.clear_todo_from_memory(session_id=session_id)
    _todo_store.clear_task_context_from_memory(session_id=session_id)
    logger.info("clear_todos session=%s removed=%d", session_id, count)
    _print_todo_action("!", f"cleared {count} item{'s' if count != 1 else ''}")
    return json.dumps(
        {
            "ok": True,
            "action": "clear_todos",
            "session_id": session_id,
        }
    )
