"""Jev Noul soft-gate for history compaction near soft thresholds."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from monitor.lib import typesafe_client as tc

logger = logging.getLogger(__name__)

QUESTION_ID = "summarize_now"


@dataclass(frozen=True)
class CompactDecision:
    summarize: bool
    noul: Optional[float]
    acted: bool
    reason: str


def decide_summarize_now(
    *,
    tokens_in_history: int,
    max_tokens: int,
    trigger_reasons: str | None = None,
) -> CompactDecision:
    """Ask whether soft-threshold compaction should run now."""
    if not tc.is_enabled():
        return CompactDecision(
            summarize=True, noul=None, acted=False, reason="jev_disabled"
        )

    response = tc.system_one(
        {
            "tokens_in_history": tokens_in_history,
            "max_tokens": max_tokens,
            "trigger_reasons": (trigger_reasons or "")[:500],
            "note": "Soft compaction threshold reached; hard overflow not yet forced.",
        },
        {
            QUESTION_ID: {
                "type": "noul",
                "instructions": (
                    "Should the coding agent compact/summarize conversation "
                    "history now to free context for continued work?"
                ),
                "criteria": {
                    "true": "Compaction now will help more than it hurts",
                    "false": "Defer; recent context is still more valuable",
                },
            }
        },
    )
    noul = tc.noul_answer(response, QUESTION_ID)
    if noul is None:
        return CompactDecision(
            summarize=True, noul=None, acted=False, reason="no_answer"
        )
    floor = tc.confidence_floor()
    summarize = noul >= floor
    logger.info(
        "Jev summarize_now noul=%.3f floor=%.3f summarize=%s",
        noul,
        floor,
        summarize,
    )
    return CompactDecision(
        summarize=summarize, noul=noul, acted=True, reason="steered"
    )


def should_soft_summarize_now(
    *,
    tokens_in_history: int,
    max_tokens: int,
    trigger_reasons: str | None = None,
) -> bool:
    """True to proceed with soft compaction (fallback allows)."""
    d = decide_summarize_now(
        tokens_in_history=tokens_in_history,
        max_tokens=max_tokens,
        trigger_reasons=trigger_reasons,
    )
    if not d.acted:
        return True
    return d.summarize
