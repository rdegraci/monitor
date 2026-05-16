"""Rate limiting helpers for Monitor OOP LLM flows."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Sequence

from monitor_oop.core.config_service import ConfigService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _UsageEvent:
    """Track a single request usage event."""

    timestamp: float
    tokens: int


@dataclass(slots=True)
class _RateLimitSnapshot:
    """Capture the active usage and limit state for a single evaluation."""

    current_tokens: int
    current_requests: int
    tpm_limit: int
    rpm_limit: int


class RateLimitService:
    """Enforce provider-aware token limits using a rolling time window."""

    def __init__(self, config_service: ConfigService, window_seconds: int = 60) -> None:
        """Initialize the rate limit service.

        Args:
            config_service: Required runtime configuration access.
            window_seconds: Rolling accounting window size in seconds.
        """

        self._config_service = config_service
        self._window_seconds = max(window_seconds, 1)
        self._usage_events: Deque[_UsageEvent] = deque()
        self._request_count_events: Deque[float] = deque()
        self._lock = threading.RLock()

    def estimate_token_usage(
        self,
        model: str,
        messages: Sequence[object],
        tools: Sequence[object] | None,
        previous_response_id: str | None,
    ) -> int:
        """Estimate token usage for a model request.

        Args:
            model: Model identifier to estimate for.
            messages: Conversation messages supplied to the model.
            tools: Optional tool definitions supplied to the model.
            previous_response_id: Optional prior response identifier for chained calls.

        Returns:
            A conservative integer estimate for the request.
        """

        estimated_tokens = self._config_service.estimate_token_usage(
            model=model,
            messages=messages,
            tools=tools,
            previous_response_id=previous_response_id,
        )
        conservative_estimate = max(int(estimated_tokens), 0)
        logger.info(
            "Estimated token usage for model=%s, messages=%s, tools=%s, previous_response_id=%s: estimated_tokens=%s, conservative_estimate=%s.",
            model,
            len(messages),
            0 if tools is None else len(tools),
            previous_response_id,
            estimated_tokens,
            conservative_estimate,
        )
        return conservative_estimate

    def request_allowed(
        self,
        model: str,
        estimated_tokens: int,
        allow_wait: bool = False,
        wait_timeout_seconds: float | None = None,
    ) -> bool:
        """Check whether a request is allowed under the active rate-limit budget.

        Args:
            model: Model identifier for the request.
            estimated_tokens: Estimated token usage for the request.
            allow_wait: Whether to wait for budget to become available.
            wait_timeout_seconds: Maximum time to wait for budget, in seconds.

        Returns:
            True when the request fits within the active budget, otherwise False.
        """

        deadline = self._compute_wait_deadline(wait_timeout_seconds)
        while True:
            with self._lock:
                self._purge_old_events_locked()
                snapshot = self._build_rate_limit_snapshot_locked(model=model)
                fits = self._fits_under_limits_locked(
                    estimated_tokens=estimated_tokens,
                    snapshot=snapshot,
                )
                logger.info(
                    "Evaluating rate limit for model=%s, estimated_tokens=%s, current_tokens=%s, current_requests=%s, tpm_limit=%s, rpm_limit=%s, window_seconds=%s, allow_wait=%s, wait_timeout_seconds=%s.",
                    model,
                    estimated_tokens,
                    snapshot.current_tokens,
                    snapshot.current_requests,
                    snapshot.tpm_limit,
                    snapshot.rpm_limit,
                    self._window_seconds,
                    allow_wait,
                    wait_timeout_seconds,
                )
                if fits:
                    logger.info(
                        "Rate limit allowed for model=%s: estimated_tokens=%s, current_tokens=%s, current_requests=%s, tpm_limit=%s, rpm_limit=%s.",
                        model,
                        estimated_tokens,
                        snapshot.current_tokens,
                        snapshot.current_requests,
                        snapshot.tpm_limit,
                        snapshot.rpm_limit,
                    )
                    return True
                if not allow_wait:
                    logger.info(
                        "Rate limit denied for model=%s without waiting: estimated_tokens=%s, current_tokens=%s, current_requests=%s, tpm_limit=%s, rpm_limit=%s.",
                        model,
                        estimated_tokens,
                        snapshot.current_tokens,
                        snapshot.current_requests,
                        snapshot.tpm_limit,
                        snapshot.rpm_limit,
                    )
                    return False
            if self._wait_timed_out(deadline, model, estimated_tokens, wait_timeout_seconds):
                return False
            time.sleep(0.1)

    def record_request(self, tokens: int) -> None:
        """Record a successful request in the rolling accounting window.

        Args:
            tokens: Actual or estimated token usage to record.
        """

        with self._lock:
            self._purge_old_events_locked()
            timestamp = datetime.now(tz=timezone.utc).timestamp()
            self._usage_events.append(_UsageEvent(timestamp=timestamp, tokens=max(tokens, 0)))
            self._request_count_events.append(timestamp)
        logger.info("Recorded rate-limit usage event: tokens=%s, timestamp=%s.", tokens, timestamp)

    def _compute_wait_deadline(self, wait_timeout_seconds: float | None) -> float | None:
        """Compute the absolute deadline for a wait attempt."""

        if wait_timeout_seconds is None:
            return None
        return time.monotonic() + max(wait_timeout_seconds, 0.0)

    def _wait_timed_out(
        self,
        deadline: float | None,
        model: str,
        estimated_tokens: int,
        wait_timeout_seconds: float | None,
    ) -> bool:
        """Check whether waiting for budget has timed out."""

        if deadline is not None and time.monotonic() >= deadline:
            logger.info(
                "Rate limit wait timed out for model=%s: estimated_tokens=%s, wait_timeout_seconds=%s.",
                model,
                estimated_tokens,
                wait_timeout_seconds,
            )
            return True
        return False

    def _build_rate_limit_snapshot_locked(self, model: str) -> _RateLimitSnapshot:
        """Collect usage and resolved limits under the active lock."""

        current_tokens, current_requests = self._current_usage_snapshot_locked()
        tpm_limit, rpm_limit = self._resolve_limits(model=model)
        return _RateLimitSnapshot(
            current_tokens=current_tokens,
            current_requests=current_requests,
            tpm_limit=tpm_limit,
            rpm_limit=rpm_limit,
        )

    def _resolve_limits(self, model: str) -> tuple[int, int]:
        """Resolve the active TPM and RPM limits for a model."""

        return self._get_tpm_limit(model), self._get_rpm_limit(model)

    def _get_tpm_limit(self, model: str) -> int:
        """Return the current TPM limit.

        Args:
            model: Model identifier for the request.

        Returns:
            The token-per-minute limit for the configured model.
        """

        limit = self._config_service.get_model_tpm_limit(model)
        if limit is None:
            conservative_fallback = 1
            logger.info(
                "No TPM limit configured for model=%s; using conservative fallback=%s.",
                model,
                conservative_fallback,
            )
            return conservative_fallback
        logger.info("Resolved TPM limit for model=%s: %s.", model, limit)
        return limit

    def _get_rpm_limit(self, model: str) -> int:
        """Return the current RPM limit.

        Args:
            model: Model identifier for the request.

        Returns:
            The request-per-minute limit for the configured model.
        """

        limit = self._config_service.get_model_rpm_limit(model)
        if limit is None:
            conservative_fallback = 1
            logger.info(
                "No RPM limit configured for model=%s; using conservative fallback=%s.",
                model,
                conservative_fallback,
            )
            return conservative_fallback
        logger.info("Resolved RPM limit for model=%s: %s.", model, limit)
        return limit

    def _current_usage_snapshot_locked(self) -> tuple[int, int]:
        """Return the current token and request usage under the active lock.

        Returns:
            A tuple containing the current token total and request count.
        """

        current_tokens = sum(event.tokens for event in self._usage_events)
        current_requests = len(self._request_count_events)
        return current_tokens, current_requests

    def _fits_under_limits_locked(
        self,
        *,
        estimated_tokens: int,
        snapshot: _RateLimitSnapshot,
    ) -> bool:
        """Check whether a request fits within the configured rate limits.

        Args:
            estimated_tokens: Estimated token usage for the request.
            snapshot: Current usage and limit state.

        Returns:
            True when the request fits within the active limits, otherwise False.
        """

        token_request_total = snapshot.current_tokens + estimated_tokens
        if token_request_total > snapshot.tpm_limit:
            logger.warning(
                "TPM limit exceeded: estimated_tokens=%s, current_tokens=%s, tpm_limit=%s",
                estimated_tokens,
                snapshot.current_tokens,
                snapshot.tpm_limit,
            )
            return False
        request_total = snapshot.current_requests + 1
        if request_total > snapshot.rpm_limit:
            logger.warning(
                "RPM limit exceeded: current_requests=%s, rpm_limit=%s",
                snapshot.current_requests,
                snapshot.rpm_limit,
            )
            return False
        return True

    def _purge_old_events_locked(self) -> None:
        """Drop usage events older than the rolling window."""

        cutoff = datetime.now(tz=timezone.utc).timestamp() - self._window_seconds
        while self._usage_events and self._usage_events[0].timestamp < cutoff:
            self._usage_events.popleft()
        while self._request_count_events and self._request_count_events[0] < cutoff:
            self._request_count_events.popleft()
