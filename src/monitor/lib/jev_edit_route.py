"""Jev edit-path routing for ``modify_source_code``.

Asks TypeSafe Choice whether a natural-language whole-file edit should
proceed, be replaced by surgical tools, or wait for more reading. Soft-fails
to allow the existing NL path when Jev is off, errors, or confidence is low.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from monitor.lib import typesafe_client as tc

logger = logging.getLogger(__name__)

QUESTION_ID = "edit_route"

ROUTE_SURGICAL = "surgical"
ROUTE_REGEN = "regen"
ROUTE_READ_MORE = "read_more"
_VALID_ROUTES = frozenset({ROUTE_SURGICAL, ROUTE_REGEN, ROUTE_READ_MORE})

_CRITERIA = {
    ROUTE_SURGICAL: (
        "The change can be expressed as exact text create/replace/insert "
        "(text_file_* or bulk_replace_in_files)."
    ),
    ROUTE_REGEN: (
        "A whole-file natural-language rewrite via modify_source_code is "
        "needed because the edit is fuzzy or spans unknown exact strings."
    ),
    ROUTE_READ_MORE: (
        "The agent should read or search the file (or related context) "
        "before editing; the modification request alone is not enough."
    ),
}

_SURGICAL_GUIDANCE = (
    "[jev_edit_route] Prefer surgical editors instead of modify_source_code. "
    "Re-read the target if needed, then use the narrowest tool: "
    "text_file_create (new file) → text_file_str_replace_in_file (unique "
    "exact replace) → text_file_insert_text_at_line → bulk_replace_in_files. "
    "Do not call modify_source_code for this change unless those tools fail."
)

_READ_MORE_GUIDANCE = (
    "[jev_edit_route] Read or search before editing. Use cat_file / "
    "cat_file_range / search tools on the target (and related files) to "
    "gather exact text, then apply a surgical text_file_* edit. Do not call "
    "modify_source_code until you have enough context for an exact change."
)


@dataclass(frozen=True)
class EditRouteDecision:
    """Outcome of an edit-path Jev Choice."""

    route: str
    """One of surgical / regen / read_more, or regen when falling back."""

    confidence: Optional[float]
    acted: bool
    """True when guidance should replace the NL modify_source_code call."""

    reason: str
    guidance: Optional[str] = None


def _build_state(
    source_file: str,
    modification_request: str,
    *,
    user_turn: Optional[str] = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "source_file": source_file,
        "modification_request": modification_request,
    }
    if user_turn and user_turn.strip():
        # Keep state small; full history is not useful for this gut-check.
        state["user_turn"] = user_turn.strip()[:2000]
    return state


def _questions() -> dict[str, Any]:
    return {
        QUESTION_ID: {
            "type": "choice",
            "instructions": (
                "A coding agent is about to call modify_source_code "
                "(natural-language whole-file rewrite) for `source_file` "
                "with `modification_request`. Which edit path should it take?"
            ),
            "criteria": dict(_CRITERIA),
        }
    }


def decide_edit_route(
    source_file: str,
    modification_request: str,
    *,
    user_turn: Optional[str] = None,
) -> EditRouteDecision:
    """Ask Jev how to handle a pending ``modify_source_code`` call.

    Returns a decision that always allows proceeding when Jev cannot act
    (disabled, error, low confidence, or ``regen``).
    """
    if not tc.is_enabled():
        return EditRouteDecision(
            route=ROUTE_REGEN,
            confidence=None,
            acted=False,
            reason="jev_disabled",
        )

    source = (source_file or "").strip() or "(unknown)"
    request = (modification_request or "").strip() or "(empty)"
    response = tc.system_one(
        _build_state(source, request, user_turn=user_turn),
        _questions(),
    )
    answer = tc.choice_answer(response, QUESTION_ID)
    if not answer:
        logger.info("Jev edit_route soft-fallback: no usable Choice answer")
        return EditRouteDecision(
            route=ROUTE_REGEN,
            confidence=None,
            acted=False,
            reason="no_answer",
        )

    choice = answer.get("choice")
    conf_raw = answer.get("confidence")
    try:
        confidence = float(conf_raw) if conf_raw is not None else None
    except (TypeError, ValueError):
        confidence = None

    if not isinstance(choice, str) or choice not in _VALID_ROUTES:
        logger.info("Jev edit_route soft-fallback: invalid choice %r", choice)
        return EditRouteDecision(
            route=ROUTE_REGEN,
            confidence=confidence,
            acted=False,
            reason="invalid_choice",
        )

    floor = tc.confidence_floor()
    if confidence is None or confidence < floor:
        logger.info(
            "Jev edit_route soft-fallback: choice=%s confidence=%s floor=%s",
            choice,
            confidence,
            floor,
        )
        return EditRouteDecision(
            route=choice,
            confidence=confidence,
            acted=False,
            reason="low_confidence",
        )

    if choice == ROUTE_REGEN:
        logger.info(
            "Jev edit_route allow regen confidence=%.3f file=%s",
            confidence,
            source,
        )
        return EditRouteDecision(
            route=ROUTE_REGEN,
            confidence=confidence,
            acted=False,
            reason="regen",
        )

    guidance = (
        _SURGICAL_GUIDANCE if choice == ROUTE_SURGICAL else _READ_MORE_GUIDANCE
    )
    logger.info(
        "Jev edit_route steer choice=%s confidence=%.3f file=%s",
        choice,
        confidence,
        source,
    )
    return EditRouteDecision(
        route=choice,
        confidence=confidence,
        acted=True,
        reason="steered",
        guidance=guidance,
    )


def maybe_steer_modify_source_code(
    function_args: Mapping[str, Any],
    *,
    user_turn: Optional[str] = None,
) -> Optional[str]:
    """Return a steering error message, or None to run ``modify_source_code``.

    Intended for use in ``tooling`` immediately before the NL edit tool runs.
    """
    source_file = function_args.get("source_file", "")
    modification_request = function_args.get("modification_request", "")
    if not isinstance(source_file, str):
        source_file = str(source_file or "")
    if not isinstance(modification_request, str):
        modification_request = str(modification_request or "")

    decision = decide_edit_route(
        source_file,
        modification_request,
        user_turn=user_turn,
    )
    if decision.acted and decision.guidance:
        return decision.guidance
    return None
