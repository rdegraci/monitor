"""Jev Noul for material scope-growth pauses on discovered work."""

from __future__ import annotations

import logging
from typing import Optional

from monitor.lib import typesafe_client as tc

logger = logging.getLogger(__name__)

QUESTION_ID = "is_material_scope_growth"

_PAUSE_NOTICE = (
    "[jev_scope] Newly discovered work looks like a material expansion of the "
    "original ask. Pause and confirm with the user before absorbing it into "
    "the plan or starting that work."
)


def should_pause_for_scope(
    item: str,
    *,
    material: bool = False,
    scope_summary: str | None = None,
) -> Optional[str]:
    """Return a pause notice string when Jev says scope grew materially.

    Soft-fail returns None (trust the model's ``material`` flag / no pause).
    """
    if not tc.is_enabled():
        return None

    text = (scope_summary or item or "").strip()
    if not text:
        return None

    # Always ask when material=true; also ask when false but item looks large.
    if not material and len(text) < 80:
        return None

    response = tc.system_one(
        {
            "discovered_item": (item or "")[:1500],
            "scope_summary": (scope_summary or "")[:1500],
            "model_claimed_material": material,
        },
        {
            QUESTION_ID: {
                "type": "noul",
                "instructions": (
                    "Does this newly discovered work materially expand the "
                    "original coding task (new feature area, large refactor, "
                    "cross-cutting work) such that the user should confirm "
                    "before the agent absorbs it?"
                ),
                "criteria": {
                    "true": "Material expansion — pause and confirm",
                    "false": "Minor discovery — safe to track without pausing",
                },
            }
        },
    )
    noul = tc.noul_answer(response, QUESTION_ID)
    if noul is None:
        return None
    floor = tc.confidence_floor()
    if noul >= floor:
        logger.info("Jev material scope pause noul=%.3f", noul)
        return _PAUSE_NOTICE
    return None
