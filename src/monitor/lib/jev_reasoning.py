"""Jev Noul gate for tool-failure reasoning escalation.

Consulted only after ``looks_like_failure`` is true. Soft-fail leaves the
existing escalate path unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from monitor.lib import typesafe_client as tc

logger = logging.getLogger(__name__)

QUESTION_ID = "escalate_reasoning"


@dataclass(frozen=True)
class EscalateDecision:
    should_escalate: bool
    """When ``acted`` is True, whether to escalate; ignored when not acted."""

    noul: Optional[float]
    acted: bool
    reason: str


def decide_escalate_on_failure(failure_text: str | None) -> EscalateDecision:
    """Ask whether tool-failure text warrants a mid-turn reasoning bump."""
    if not tc.is_enabled():
        return EscalateDecision(
            should_escalate=True,
            noul=None,
            acted=False,
            reason="jev_disabled",
        )
    text = (failure_text or "").strip()
    if not text:
        return EscalateDecision(
            should_escalate=True,
            noul=None,
            acted=False,
            reason="empty_text",
        )

    response = tc.system_one(
        {"tool_output": text[:3000]},
        {
            QUESTION_ID: {
                "type": "noul",
                "instructions": (
                    "This tool output was flagged as a failure. Should the "
                    "coding agent escalate reasoning effort for the rest of "
                    "this turn to diagnose and fix it?"
                ),
                "criteria": {
                    "true": "Real failure that needs deeper reasoning to fix",
                    "false": "Benign, informational, or not worth escalating",
                },
            }
        },
    )
    noul = tc.noul_answer(response, QUESTION_ID)
    if noul is None:
        return EscalateDecision(
            should_escalate=True,
            noul=None,
            acted=False,
            reason="no_answer",
        )

    floor = tc.confidence_floor()
    escalate = noul >= floor
    logger.info(
        "Jev escalate_reasoning noul=%.3f floor=%.3f escalate=%s",
        noul,
        floor,
        escalate,
    )
    return EscalateDecision(
        should_escalate=escalate,
        noul=noul,
        acted=True,
        reason="steered",
    )


def should_jev_allow_escalate(failure_text: str | None) -> bool:
    """True if escalation should proceed (Jev yes, or soft-fallback to allow)."""
    decision = decide_escalate_on_failure(failure_text)
    if not decision.acted:
        return True
    return decision.should_escalate
