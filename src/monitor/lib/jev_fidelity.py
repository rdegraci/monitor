"""Jev Score for compaction summary fidelity (soft path only)."""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from monitor.lib import typesafe_client as tc

logger = logging.getLogger(__name__)

QUESTION_ID = "summary_fidelity"


def summary_is_faithful_enough(
    summary_text: str,
    *,
    history_excerpt: str | None = None,
) -> bool:
    """Return False when Jev is confident the summary drops critical coding context.

    Soft-fail returns True (accept summary as today).
    """
    if not tc.is_enabled():
        return True
    text = (summary_text or "").strip()
    if not text:
        return False

    state: dict[str, Any] = {"summary": text[:4000]}
    if history_excerpt:
        state["history_excerpt"] = history_excerpt[:3000]

    response = tc.system_one(
        state,
        {
            QUESTION_ID: {
                "type": "score",
                "instructions": (
                    "For continuing a coding session, how well does `summary` "
                    "preserve critical context (files, failing tests, "
                    "acceptance criteria, open bugs)?"
                ),
                "criteria": [
                    "Drops critical context — unsafe to replace history",
                    "Weak — major gaps likely",
                    "Adequate for continuation",
                    "Strong fidelity",
                ],
            }
        },
    )
    answer = tc.score_answer(response, QUESTION_ID)
    if not answer:
        return True
    try:
        conf = (
            float(answer["confidence"])
            if answer.get("confidence") is not None
            else None
        )
        score = float(answer.get("score"))
    except (TypeError, ValueError):
        return True
    floor = tc.confidence_floor()
    if conf is None or conf < floor:
        return True
    # Scores are ~0..3; require at least "Adequate" (2.0) when confident.
    ok = score >= 2.0
    logger.info(
        "Jev summary_fidelity score=%.2f conf=%.2f ok=%s", score, conf, ok
    )
    return ok


def history_excerpt_for_fidelity(history: Sequence[Any], *, max_chars: int = 3000) -> str:
    """Build a small excerpt from recent non-system messages."""
    parts: list[str] = []
    for msg in reversed(list(history)):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "system":
            continue
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        parts.append(f"{role}: {content.strip()[:800]}")
        if sum(len(p) for p in parts) >= max_chars:
            break
    parts.reverse()
    text = "\n".join(parts)
    return text[:max_chars]
