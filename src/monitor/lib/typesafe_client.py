"""Thin TypeSafe / Jev System One HTTP client for Monitor.

Uses core ``requests`` only (no required typesafe-sdk). Soft-fails when the
API key is missing, the kill-switch is off, or the endpoint errors — callers
must treat ``None`` answers as “use pre-Jev behavior.”
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Mapping, MutableMapping, Optional

import requests

logger = logging.getLogger(__name__)

SYSTEM_ONE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT_SEC = 30.0
DEFAULT_CONFIDENCE_FLOOR = 0.6
_RETRYABLE_STATUS = frozenset({429, 529})
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SEC = (0.5, 1.0, 2.0)

# Kill-switch values that disable Jev even when TYPESAFE_API_KEY is set.
_KILL_SWITCH_OFF = frozenset({"0", "false", "off", "no", "disable", "disabled"})


def _env_truthy_off(name: str) -> bool:
    """Return True when env ``name`` is set to a recognized off value."""
    raw = os.environ.get(name)
    if raw is None:
        return False
    return raw.strip().lower() in _KILL_SWITCH_OFF


def api_key() -> Optional[str]:
    """Return ``TYPESAFE_API_KEY`` when non-empty, else None."""
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    return key or None


def is_enabled() -> bool:
    """True when Jev may be called (key present and kill-switch not off)."""
    if _env_truthy_off("MONITOR_JEV"):
        return False
    return api_key() is not None


def confidence_floor() -> float:
    """Minimum Choice/Score confidence to act on a Jev route."""
    raw = os.environ.get("MONITOR_JEV_CONFIDENCE", "").strip()
    if not raw:
        return DEFAULT_CONFIDENCE_FLOOR
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "Invalid MONITOR_JEV_CONFIDENCE=%r; using default %.2f",
            raw,
            DEFAULT_CONFIDENCE_FLOOR,
        )
        return DEFAULT_CONFIDENCE_FLOOR
    if value < 0.0 or value > 1.0:
        logger.warning(
            "MONITOR_JEV_CONFIDENCE out of range (%s); using default %.2f",
            value,
            DEFAULT_CONFIDENCE_FLOOR,
        )
        return DEFAULT_CONFIDENCE_FLOOR
    return value


def system_one(
    state: Any,
    questions: Mapping[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> Optional[dict[str, Any]]:
    """POST a System One evaluation; return the JSON body or None on soft fail.

    Args:
        state: Text or structured state for Jev.
        questions: Named question map (noul / choice / score).
        model: Model id or alias (default ``jev-latest``).
        timeout: Per-request timeout in seconds.

    Returns:
        Parsed response dict on success, or None when disabled or on error.
    """
    if not is_enabled():
        logger.debug("TypeSafe Jev disabled (no key or MONITOR_JEV off)")
        return None

    key = api_key()
    if key is None:
        return None

    payload: dict[str, Any] = {
        "state": state,
        "model": model,
        "questions": dict(questions),
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    last_error: Optional[BaseException] = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = requests.post(
                SYSTEM_ONE_URL,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_error = exc
            logger.warning(
                "TypeSafe request failed (attempt %d/%d): %s",
                attempt + 1,
                _MAX_ATTEMPTS,
                exc,
            )
            if attempt + 1 < _MAX_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SEC[min(attempt, len(_RETRY_BACKOFF_SEC) - 1)])
                continue
            return None

        if response.status_code in _RETRYABLE_STATUS:
            logger.warning(
                "TypeSafe status %s (attempt %d/%d)",
                response.status_code,
                attempt + 1,
                _MAX_ATTEMPTS,
            )
            if attempt + 1 < _MAX_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SEC[min(attempt, len(_RETRY_BACKOFF_SEC) - 1)])
                continue
            return None

        if response.status_code in (401, 402, 422):
            logger.warning(
                "TypeSafe soft-fail status %s: %s",
                response.status_code,
                (response.text or "")[:300],
            )
            return None

        if response.status_code >= 400:
            logger.warning(
                "TypeSafe soft-fail status %s: %s",
                response.status_code,
                (response.text or "")[:300],
            )
            return None

        try:
            data = response.json()
        except ValueError as exc:
            last_error = exc
            logger.warning("TypeSafe response was not JSON: %s", exc)
            return None

        if not isinstance(data, dict):
            logger.warning("TypeSafe response JSON was not an object")
            return None
        return data

    if last_error is not None:
        logger.debug("TypeSafe giving up after errors: %s", last_error)
    return None


def choice_answer(
    response: Optional[Mapping[str, Any]],
    question_id: str,
) -> Optional[MutableMapping[str, Any]]:
    """Extract a Choice answer dict for ``question_id``, or None."""
    if not response:
        return None
    answers = response.get("answers")
    if not isinstance(answers, Mapping):
        return None
    answer = answers.get(question_id)
    if not isinstance(answer, Mapping):
        return None
    if answer.get("type") != "choice":
        return None
    return dict(answer)
