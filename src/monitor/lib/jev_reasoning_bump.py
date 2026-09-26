"""Jev Noul backstop for proactive per-turn reasoning bumps.

Keyword/length heuristics stay primary. Jev confirms heuristic bumps and
can promote mid-length ambiguous asks that the heuristic missed.
"""

from __future__ import annotations

import logging
from typing import Optional

from monitor.lib import typesafe_client as tc
from monitor.lib.reasoning_heuristic import (
    LENGTH_THRESHOLD,
    LINE_COUNT_THRESHOLD,
    _effective_bump_target,
    detect_reasoning_bump,
)

logger = logging.getLogger(__name__)

QUESTION_ID = "should_bump_reasoning"

# Mid-band: too long for a one-liner, below the hard length trigger.
_MID_LEN_LOW = 200


def _is_mid_ambiguous(user_text: str) -> bool:
    n = len(user_text)
    lines = user_text.count("\n") + 1
    if _MID_LEN_LOW <= n <= LENGTH_THRESHOLD:
        return True
    if 2 <= lines <= LINE_COUNT_THRESHOLD:
        return True
    return False


def _noul_should_bump(user_text: str) -> Optional[bool]:
    """Return True/False when Jev acts; None on soft-fail."""
    if not tc.is_enabled():
        return None
    response = tc.system_one(
        {"user_turn": user_text[:2000]},
        {
            QUESTION_ID: {
                "type": "noul",
                "instructions": (
                    "Should the coding agent raise reasoning effort for this "
                    "user turn (deeper thinking for diagnosis, design, or "
                    "multi-step correctness)?"
                ),
                "criteria": {
                    "true": "Hard / diagnostic / high-stakes; bump effort",
                    "false": "Routine edit or simple ask; keep default effort",
                },
            }
        },
    )
    noul = tc.noul_answer(response, QUESTION_ID)
    if noul is None:
        return None
    floor = tc.confidence_floor()
    return noul >= floor


def resolve_reasoning_bump(
    user_text: str | None,
    current_effort: str | None,
    bump_floor=None,
) -> Optional[str]:
    """Return bump target effort, or None to leave default.

    Soft-fail preserves ``detect_reasoning_bump`` behavior.
    """
    if not user_text or not isinstance(user_text, str):
        return None

    target = _effective_bump_target(bump_floor)
    heuristic = detect_reasoning_bump(user_text, current_effort, bump_floor=bump_floor)

    if heuristic:
        decision = _noul_should_bump(user_text)
        if decision is None:
            return heuristic
        if decision:
            logger.info("Jev confirmed reasoning bump → %s", heuristic)
            return heuristic
        logger.info("Jev declined heuristic reasoning bump; keeping default")
        return None

    # Heuristic miss: optional mid-band promotion.
    if not _is_mid_ambiguous(user_text):
        return None

    # Only if bump would actually raise effort.
    from monitor.lib.reasoning_heuristic import _EFFORT_RANK, _BUMP_TARGET

    current_rank = _EFFORT_RANK.get(
        (current_effort or "").lower(), _EFFORT_RANK["low"]
    )
    if current_rank >= _EFFORT_RANK.get(target, _EFFORT_RANK[_BUMP_TARGET]):
        return None

    decision = _noul_should_bump(user_text)
    if decision is True:
        logger.info("Jev mid-band reasoning bump → %s", target)
        return target
    return None
