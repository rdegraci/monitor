"""Jev tool-group auto-widen when regex intent detection finds nothing.

Regex remains primary for explicit phrases. Jev only runs as a backstop on
ambiguous user text, with soft fallback to no extra widen.

Avoid importing ``tool_profiles`` here — that module participates in a load
cycle with ``config`` / ``llm_utils``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Set

from monitor.lib import typesafe_client as tc

logger = logging.getLogger(__name__)

QUESTION_ID = "tool_group"

NETWORK_GROUP = "network"
DB_GROUP = "db"
AGENT_GROUP = "agent"
VERIFY_GROUP = "verify"
EDIT_GROUP = "edit"
MEMORY_GROUP = "memory"
ROUTE_NONE = "none"

_VALID = frozenset(
    {
        NETWORK_GROUP,
        DB_GROUP,
        AGENT_GROUP,
        VERIFY_GROUP,
        EDIT_GROUP,
        MEMORY_GROUP,
        ROUTE_NONE,
    }
)

_CRITERIA = {
    NETWORK_GROUP: "User needs web search, online lookup, or Tavily.",
    DB_GROUP: "User needs SQL / Postgres / DuckDB / database inspection.",
    AGENT_GROUP: "User wants to spawn or orchestrate sub-agents.",
    VERIFY_GROUP: "User wants tests, typecheck, audit, or code review tools.",
    EDIT_GROUP: "User wants to edit/fix/implement code (write tools).",
    MEMORY_GROUP: "User wants session memory remember/forget tools.",
    ROUTE_NONE: "No temporary tool-group widen is needed.",
}


@dataclass(frozen=True)
class ToolRouteDecision:
    group: Optional[str]
    """Chosen auto-widenable group, or None for none/fallback."""

    confidence: Optional[float]
    acted: bool
    reason: str


def decide_tool_group(user_text: str | None) -> ToolRouteDecision:
    """Ask Jev which temporary tool group fits ambiguous user text."""
    if not tc.is_enabled():
        return ToolRouteDecision(
            group=None, confidence=None, acted=False, reason="jev_disabled"
        )
    text = (user_text or "").strip()
    if not text:
        return ToolRouteDecision(
            group=None, confidence=None, acted=False, reason="empty_text"
        )

    state = {"user_turn": text[:2000]}
    response = tc.system_one(
        state,
        {
            QUESTION_ID: {
                "type": "choice",
                "instructions": (
                    "Which temporary Monitor tool group should be leased for "
                    "this user turn? Prefer `none` unless the request clearly "
                    "needs a withheld group."
                ),
                "criteria": dict(_CRITERIA),
            }
        },
    )
    answer = tc.choice_answer(response, QUESTION_ID)
    if not answer:
        return ToolRouteDecision(
            group=None, confidence=None, acted=False, reason="no_answer"
        )

    choice = answer.get("choice")
    try:
        confidence = (
            float(answer["confidence"]) if answer.get("confidence") is not None else None
        )
    except (TypeError, ValueError):
        confidence = None

    if not isinstance(choice, str) or choice not in _VALID:
        return ToolRouteDecision(
            group=None, confidence=confidence, acted=False, reason="invalid_choice"
        )

    floor = tc.confidence_floor()
    if confidence is None or confidence < floor:
        return ToolRouteDecision(
            group=None if choice == ROUTE_NONE else choice,
            confidence=confidence,
            acted=False,
            reason="low_confidence",
        )

    if choice == ROUTE_NONE:
        logger.info("Jev tool_group chose none confidence=%.3f", confidence)
        return ToolRouteDecision(
            group=None, confidence=confidence, acted=True, reason="none"
        )

    logger.info("Jev tool_group chose %s confidence=%.3f", choice, confidence)
    return ToolRouteDecision(
        group=choice, confidence=confidence, acted=True, reason="steered"
    )


def maybe_jev_auto_widen_groups(user_text: str | None) -> Set[str]:
    """Return a set of groups to widen when Jev acts; empty otherwise."""
    decision = decide_tool_group(user_text)
    if decision.acted and decision.group:
        return {decision.group}
    return set()
