"""Jev harvest classification for background sub-agent results."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from monitor.lib import typesafe_client as tc

logger = logging.getLogger(__name__)

STATUS_ID = "harvest_status"
QUALITY_ID = "finding_quality"

STATUS_DONE = "done"
STATUS_BLOCKED = "blocked"
STATUS_NEEDS_ORCHESTRATOR = "needs_orchestrator"
_VALID_STATUS = frozenset(
    {STATUS_DONE, STATUS_BLOCKED, STATUS_NEEDS_ORCHESTRATOR}
)


@dataclass(frozen=True)
class HarvestDecision:
    status: Optional[str]
    quality_score: Optional[float]
    quality_confidence: Optional[float]
    acted: bool
    reason: str
    prefix: Optional[str] = None


def decide_harvest(summary: str | None) -> HarvestDecision:
    """Classify a sub-agent terminal summary for orchestrator routing."""
    if not tc.is_enabled():
        return HarvestDecision(
            status=None,
            quality_score=None,
            quality_confidence=None,
            acted=False,
            reason="jev_disabled",
        )
    text = (summary or "").strip()
    if not text:
        return HarvestDecision(
            status=None,
            quality_score=None,
            quality_confidence=None,
            acted=False,
            reason="empty",
        )

    response = tc.system_one(
        {"subagent_summary": text[:4000]},
        {
            STATUS_ID: {
                "type": "choice",
                "instructions": (
                    "Classify this background sub-agent result for the "
                    "orchestrator coding agent."
                ),
                "criteria": {
                    STATUS_DONE: "Complete enough findings; orchestrator can apply or close",
                    STATUS_BLOCKED: "Sub-agent failed or could not finish",
                    STATUS_NEEDS_ORCHESTRATOR: (
                        "Needs orchestrator judgment, merge, or follow-up work"
                    ),
                },
            },
            QUALITY_ID: {
                "type": "score",
                "instructions": "How useful are these findings for the orchestrator?",
                "criteria": [
                    "Empty or noise",
                    "Partial or weak signal",
                    "Actionable findings",
                    "High-signal, ready to use",
                ],
            },
        },
    )
    choice = tc.choice_answer(response, STATUS_ID)
    score = tc.score_answer(response, QUALITY_ID)
    if not choice:
        return HarvestDecision(
            status=None,
            quality_score=None,
            quality_confidence=None,
            acted=False,
            reason="no_answer",
        )

    status = choice.get("choice")
    try:
        conf = (
            float(choice["confidence"]) if choice.get("confidence") is not None else None
        )
    except (TypeError, ValueError):
        conf = None

    q_score = None
    q_conf = None
    if score:
        try:
            q_score = float(score.get("score")) if score.get("score") is not None else None
        except (TypeError, ValueError):
            q_score = None
        try:
            q_conf = (
                float(score["confidence"])
                if score.get("confidence") is not None
                else None
            )
        except (TypeError, ValueError):
            q_conf = None

    if not isinstance(status, str) or status not in _VALID_STATUS:
        return HarvestDecision(
            status=None,
            quality_score=q_score,
            quality_confidence=q_conf,
            acted=False,
            reason="invalid_choice",
        )

    floor = tc.confidence_floor()
    if conf is None or conf < floor:
        return HarvestDecision(
            status=status,
            quality_score=q_score,
            quality_confidence=q_conf,
            acted=False,
            reason="low_confidence",
        )

    prefix = (
        f"[jev_harvest status={status}"
        + (f" quality={q_score:.2f}" if isinstance(q_score, float) else "")
        + "]"
    )
    logger.info(
        "Jev harvest status=%s conf=%.3f quality=%s", status, conf, q_score
    )
    return HarvestDecision(
        status=status,
        quality_score=q_score,
        quality_confidence=q_conf,
        acted=True,
        reason="steered",
        prefix=prefix,
    )


def annotate_injection(text: str) -> str:
    """Prepend harvest metadata when Jev acts; otherwise return text unchanged."""
    decision = decide_harvest(text)
    if decision.acted and decision.prefix:
        return f"{decision.prefix} {text}"
    return text
