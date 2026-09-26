"""Jev Score for plan / next-steps quality (keeps parsed steps; adds note)."""

from __future__ import annotations

import logging
from typing import List

from monitor.lib import typesafe_client as tc

logger = logging.getLogger(__name__)

QUESTION_ID = "plan_quality"


def annotate_steps_quality(summary: str, steps: List[str]) -> List[str]:
    """Optionally prefix steps with a quality note when Jev acts."""
    if not steps or not tc.is_enabled():
        return steps
    response = tc.system_one(
        {
            "branch_summary": (summary or "")[:2000],
            "next_steps": steps[:8],
        },
        {
            QUESTION_ID: {
                "type": "score",
                "instructions": "How actionable and well-scoped are these next steps?",
                "criteria": [
                    "Vague or unhelpful",
                    "Somewhat useful",
                    "Clear and actionable",
                    "Excellent, prioritized plan",
                ],
            }
        },
    )
    answer = tc.score_answer(response, QUESTION_ID)
    if not answer:
        return steps
    try:
        score = float(answer.get("score"))
        conf = float(answer.get("confidence")) if answer.get("confidence") is not None else None
    except (TypeError, ValueError):
        return steps
    floor = tc.confidence_floor()
    if conf is None or conf < floor:
        return steps
    note = f"[jev_next_steps quality={score:.2f}]"
    logger.info("Jev next_steps %s", note)
    return [note, *steps]
