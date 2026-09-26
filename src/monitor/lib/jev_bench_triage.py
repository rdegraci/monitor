"""Optional Jev triage for monitor_bench failed samples."""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from monitor.lib import typesafe_client as tc

logger = logging.getLogger(__name__)

QUESTION_ID = "bench_triage"


def triage_failed_sample(
    detail: str | None,
    *,
    history_excerpt: str | None = None,
) -> Optional[str]:
    """Return ``flake`` or ``real_regression`` when Jev acts; else None."""
    if not tc.is_enabled():
        return None
    state: dict[str, Any] = {
        "grade_detail": (detail or "")[:2000],
    }
    if history_excerpt:
        state["history_excerpt"] = history_excerpt[:3000]
    response = tc.system_one(
        state,
        {
            QUESTION_ID: {
                "type": "choice",
                "instructions": (
                    "A coding-agent bench sample failed. Is this likely a flake "
                    "or a real regression?"
                ),
                "criteria": {
                    "flake": "Transient / flaky / environment noise",
                    "real_regression": "Likely a real product or agent regression",
                },
            }
        },
    )
    answer = tc.choice_answer(response, QUESTION_ID)
    if not answer:
        return None
    choice = answer.get("choice")
    try:
        conf = (
            float(answer["confidence"]) if answer.get("confidence") is not None else None
        )
    except (TypeError, ValueError):
        conf = None
    if choice not in ("flake", "real_regression"):
        return None
    floor = tc.confidence_floor()
    if conf is None or conf < floor:
        return None
    logger.info("Jev bench_triage=%s confidence=%s", choice, conf)
    return choice


def annotate_sample_result(sample: Mapping[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with optional ``jev_triage`` when failed."""
    out = dict(sample)
    if sample.get("passed"):
        return out
    label = triage_failed_sample(
        sample.get("detail") if isinstance(sample.get("detail"), str) else None,
    )
    if label:
        out["jev_triage"] = label
    return out
