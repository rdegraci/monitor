"""Jev acceptance gate when marking a todo done (steer-only)."""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from monitor.lib import typesafe_client as tc

logger = logging.getLogger(__name__)

QUESTION_ID = "acceptance_met"


def maybe_steer_todo_done(
    todo_entry: Mapping[str, Any],
    *,
    acceptance_criteria: list | None = None,
    recent_context: str | None = None,
) -> Optional[str]:
    """Return guidance if done looks premature; None to allow the status change.

    Soft-fail allows done (pre-Jev behavior).
    """
    if not tc.is_enabled():
        return None

    item = str(todo_entry.get("item") or "").strip()
    notes = str(todo_entry.get("notes") or "").strip()
    if not item:
        return None

    criteria = acceptance_criteria or []
    criteria_text = "\n".join(f"- {c}" for c in criteria[:12] if c)

    state = {
        "todo_item": item[:1500],
        "todo_notes": notes[:1000],
        "acceptance_criteria": criteria_text[:2000] or "(none recorded)",
    }
    if recent_context:
        state["recent_context"] = recent_context[:2000]

    response = tc.system_one(
        state,
        {
            QUESTION_ID: {
                "type": "noul",
                "instructions": (
                    "The coding agent wants to mark this todo done. Given the "
                    "item, notes, and acceptance criteria, has the work likely "
                    "been completed adequately?"
                ),
                "criteria": {
                    "true": "Acceptable to mark done",
                    "false": "Premature — criteria or work still incomplete",
                },
            }
        },
    )
    noul = tc.noul_answer(response, QUESTION_ID)
    if noul is None:
        return None
    floor = tc.confidence_floor()
    if noul >= floor:
        return None

    logger.info("Jev acceptance_met low noul=%.3f; steering away from done", noul)
    return (
        "[jev_acceptance] Marking this todo done looks premature relative to "
        "the item/acceptance criteria. Keep it in_progress (or blocked) and "
        "finish the remaining work before setting status=done."
    )
