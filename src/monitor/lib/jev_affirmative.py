"""Jev affirmative / continue gate for offer acceptance.

Choice ``proceed`` / ``ask`` / ``decline``. Soft-fail leaves prompt-only
behavior (caller treats non-acted as proceed-compatible with today).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from monitor.lib import typesafe_client as tc

logger = logging.getLogger(__name__)

QUESTION_ID = "affirmative"

ROUTE_PROCEED = "proceed"
ROUTE_ASK = "ask"
ROUTE_DECLINE = "decline"
_VALID = frozenset({ROUTE_PROCEED, ROUTE_ASK, ROUTE_DECLINE})

_OFFER_RE = re.compile(
    r"(?i)(if you want|would you like|should i|shall i|let me know|"
    r"want me to|i can\b.{0,40}\b(for you|next)|confirm\?)"
)
_SHORT_AFFIRM_RE = re.compile(
    r"(?i)^\s*(yes|y|ok|okay|go|go ahead|proceed|do it|sounds good|"
    r"start|start now|continue|next|do that|sure|yep|yeah)\s*[.!]*\s*$"
)


@dataclass(frozen=True)
class AffirmativeDecision:
    route: str
    confidence: Optional[float]
    acted: bool
    reason: str


def looks_like_offer(assistant_text: str | None) -> bool:
    if not assistant_text or not isinstance(assistant_text, str):
        return False
    return bool(_OFFER_RE.search(assistant_text))


def looks_like_short_affirmative(user_text: str | None) -> bool:
    if not user_text or not isinstance(user_text, str):
        return False
    return bool(_SHORT_AFFIRM_RE.match(user_text.strip()))


def decide_affirmative(
    user_text: str | None,
    pending_offer: str | None,
) -> AffirmativeDecision:
    """Decide whether to proceed with a pending offer after a short user reply."""
    if not tc.is_enabled():
        return AffirmativeDecision(
            route=ROUTE_PROCEED, confidence=None, acted=False, reason="jev_disabled"
        )
    user = (user_text or "").strip()
    offer = (pending_offer or "").strip()
    if not user or not offer:
        return AffirmativeDecision(
            route=ROUTE_PROCEED, confidence=None, acted=False, reason="missing_context"
        )

    response = tc.system_one(
        {
            "pending_offer": offer[:2000],
            "user_reply": user[:500],
        },
        {
            QUESTION_ID: {
                "type": "choice",
                "instructions": (
                    "The assistant made an offer. The user replied. Should the "
                    "agent proceed with the offer, ask for clarification, or treat "
                    "the reply as a decline?"
                ),
                "criteria": {
                    ROUTE_PROCEED: "Clear acceptance; execute the offered work",
                    ROUTE_ASK: "Ambiguous; ask before running tools",
                    ROUTE_DECLINE: "User declined or changed the subject",
                },
            }
        },
    )
    answer = tc.choice_answer(response, QUESTION_ID)
    if not answer:
        return AffirmativeDecision(
            route=ROUTE_PROCEED, confidence=None, acted=False, reason="no_answer"
        )

    choice = answer.get("choice")
    try:
        confidence = (
            float(answer["confidence"]) if answer.get("confidence") is not None else None
        )
    except (TypeError, ValueError):
        confidence = None

    if not isinstance(choice, str) or choice not in _VALID:
        return AffirmativeDecision(
            route=ROUTE_ASK, confidence=confidence, acted=False, reason="invalid_choice"
        )

    floor = tc.confidence_floor()
    if confidence is None or confidence < floor:
        # Safe default when uncertain: ask.
        return AffirmativeDecision(
            route=ROUTE_ASK, confidence=confidence, acted=True, reason="low_confidence_ask"
        )

    logger.info(
        "Jev affirmative choice=%s confidence=%.3f", choice, confidence
    )
    return AffirmativeDecision(
        route=choice, confidence=confidence, acted=True, reason="steered"
    )


def maybe_gate_affirmative(
    user_text: str | None,
    pending_offer: str | None,
) -> Optional[str]:
    """Return a steer message when the agent should ask/decline; else None.

    ``None`` means proceed with current behavior (including soft-fail).
    """
    if not looks_like_offer(pending_offer):
        return None
    if not looks_like_short_affirmative(user_text):
        return None
    decision = decide_affirmative(user_text, pending_offer)
    if not decision.acted:
        return None
    if decision.route == ROUTE_PROCEED:
        return None
    if decision.route == ROUTE_DECLINE:
        return (
            "[jev_affirmative] Treat the user reply as declining the pending "
            "offer. Do not start tool execution for that offer; acknowledge and wait."
        )
    return (
        "[jev_affirmative] The user reply is ambiguous. Ask a brief clarifying "
        "question before running tools for the pending offer."
    )
