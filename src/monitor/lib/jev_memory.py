"""Jev Noul gate for SemanticStore: skip empty remembers without an LLM call."""

from __future__ import annotations

import logging
from typing import Optional

from monitor.lib import typesafe_client as tc

logger = logging.getLogger(__name__)

QUESTION_ID = "should_remember"


def should_attempt_remember(user_prompt: str | None) -> bool:
    """Return False when Jev is confident nothing durable should be stored.

    Soft-fail (disabled/error) returns True so the existing LLM path runs.
    """
    if not tc.is_enabled():
        return True
    text = (user_prompt or "").strip()
    if not text:
        return False

    response = tc.system_one(
        {"user_message": text[:3000]},
        {
            QUESTION_ID: {
                "type": "noul",
                "instructions": (
                    "Does this message contain a durable fact, preference, or "
                    "instruction worth storing in long-term session memory?"
                ),
                "criteria": {
                    "true": "Yes — store-worthy durable information",
                    "false": "No — ephemeral or not worth remembering",
                },
            }
        },
    )
    noul = tc.noul_answer(response, QUESTION_ID)
    if noul is None:
        return True
    floor = tc.confidence_floor()
    remember = noul >= floor
    logger.info(
        "Jev should_remember noul=%.3f floor=%.3f remember=%s",
        noul,
        floor,
        remember,
    )
    return remember
