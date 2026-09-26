"""Jev review ship-gate: ship / revise / block with composite Scores."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from monitor.lib import typesafe_client as tc

logger = logging.getLogger(__name__)

DECISION_ID = "ship_decision"
CORRECTNESS_ID = "correctness"
RISK_ID = "risk"
TEST_GAPS_ID = "test_gaps"

ROUTE_SHIP = "ship"
ROUTE_REVISE = "revise"
ROUTE_BLOCK = "block"
_VALID = frozenset({ROUTE_SHIP, ROUTE_REVISE, ROUTE_BLOCK})

# Higher composite favors shipping; weights live in code (not prompts).
_WEIGHTS = {
    CORRECTNESS_ID: 0.45,
    RISK_ID: 0.30,  # inverted: high risk lowers composite
    TEST_GAPS_ID: 0.25,  # inverted: more gaps lowers composite
}


@dataclass(frozen=True)
class ReviewGateDecision:
    route: str
    confidence: Optional[float]
    composite: Optional[float]
    acted: bool
    reason: str
    message: Optional[str] = None


def _score_value(response, question_id: str) -> Optional[float]:
    answer = tc.score_answer(response, question_id)
    if not answer:
        return None
    try:
        return float(answer.get("score"))
    except (TypeError, ValueError):
        return None


def decide_review_gate(diff_or_summary: str | None) -> ReviewGateDecision:
    """Evaluate a review diff/summary for ship readiness."""
    if not tc.is_enabled():
        return ReviewGateDecision(
            route=ROUTE_REVISE,
            confidence=None,
            composite=None,
            acted=False,
            reason="jev_disabled",
        )
    text = (diff_or_summary or "").strip()
    if not text:
        return ReviewGateDecision(
            route=ROUTE_REVISE,
            confidence=None,
            composite=None,
            acted=False,
            reason="empty",
        )

    response = tc.system_one(
        {"review_material": text[:6000]},
        {
            DECISION_ID: {
                "type": "choice",
                "instructions": (
                    "Given this code review material, should we ship, revise, or block?"
                ),
                "criteria": {
                    ROUTE_SHIP: "Safe to merge/ship with current changes",
                    ROUTE_REVISE: "Needs more work before shipping",
                    ROUTE_BLOCK: "Serious risk; do not ship",
                },
            },
            CORRECTNESS_ID: {
                "type": "score",
                "instructions": "Correctness of the change",
                "criteria": [
                    "Likely wrong or incomplete",
                    "Mixed / uncertain",
                    "Mostly correct",
                    "Clearly correct",
                ],
            },
            RISK_ID: {
                "type": "score",
                "instructions": "Operational / security / data risk",
                "criteria": [
                    "Low risk",
                    "Moderate risk",
                    "High risk",
                    "Severe risk",
                ],
            },
            TEST_GAPS_ID: {
                "type": "score",
                "instructions": "Test coverage gaps for this change",
                "criteria": [
                    "Well covered",
                    "Some gaps",
                    "Large gaps",
                    "No meaningful tests",
                ],
            },
        },
    )
    choice = tc.choice_answer(response, DECISION_ID)
    if not choice:
        return ReviewGateDecision(
            route=ROUTE_REVISE,
            confidence=None,
            composite=None,
            acted=False,
            reason="no_answer",
        )

    route = choice.get("choice")
    try:
        conf = (
            float(choice["confidence"]) if choice.get("confidence") is not None else None
        )
    except (TypeError, ValueError):
        conf = None

    correctness = _score_value(response, CORRECTNESS_ID)
    risk = _score_value(response, RISK_ID)
    gaps = _score_value(response, TEST_GAPS_ID)
    composite = None
    if None not in (correctness, risk, gaps):
        # Scores are 0..3-ish; normalize roughly by /3. Invert risk and gaps.
        composite = (
            _WEIGHTS[CORRECTNESS_ID] * (correctness / 3.0)
            + _WEIGHTS[RISK_ID] * (1.0 - (risk / 3.0))
            + _WEIGHTS[TEST_GAPS_ID] * (1.0 - (gaps / 3.0))
        )

    if not isinstance(route, str) or route not in _VALID:
        return ReviewGateDecision(
            route=ROUTE_REVISE,
            confidence=conf,
            composite=composite,
            acted=False,
            reason="invalid_choice",
        )

    floor = tc.confidence_floor()
    if conf is None or conf < floor:
        return ReviewGateDecision(
            route=route,
            confidence=conf,
            composite=composite,
            acted=False,
            reason="low_confidence",
        )

    msg = (
        f"[jev_review_gate] decision={route}"
        + (f" confidence={conf:.2f}" if conf is not None else "")
        + (f" composite={composite:.2f}" if composite is not None else "")
    )
    logger.info("%s", msg)
    return ReviewGateDecision(
        route=route,
        confidence=conf,
        composite=composite,
        acted=True,
        reason="steered",
        message=msg,
    )
