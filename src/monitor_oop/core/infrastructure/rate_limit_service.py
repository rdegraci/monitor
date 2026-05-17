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

LEGACY_RATE_LIMIT_BUCKET = "__legacy__"


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
    rpm_limit: int | None


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
        self._usage_events: dict[str, Deque[_UsageEvent]] = {}
        self._request_count_events: dict[str, Deque[float]] = {}
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

        accounting_key = self._resolve_rate_limit_key(model=model)
        deadline = self._compute_wait_deadline(wait_timeout_seconds)
        while True:
            with self._lock:
                self._purge_old_events_locked(accounting_key)
                snapshot = self._build_rate_limit_snapshot_locked(model=model, accounting_key=accounting_key)
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
        """Record a successful request in the legacy compatibility bucket.

        Args:
            tokens: Actual or estimated token usage to record.

        This path preserves the legacy compatibility bucket behavior for callers
        that do not track usage by model.
        """

        self._record_request_for_bucket(bucket=LEGACY_RATE_LIMIT_BUCKET, tokens=tokens)

    def record_request_for_model(self, model: str, tokens: int) -> None:
        """Record a successful request for a specific model.

        Args:
            model: Model identifier used for accounting.
            tokens: Actual or estimated token usage to record.

        This is the public model-aware recording path; it delegates to the
        existing internal model-scoped implementation and preserves the current
        logging behavior.
        """

        self._record_request_for_model(model=model, tokens=tokens)

    def _record_request_for_model(self, model: str, tokens: int) -> None:
        """Record a successful request for a specific model in the rolling accounting window.

        Args:
            model: Model identifier used for accounting.
            tokens: Actual or estimated token usage to record.
        """

        accounting_key = self._resolve_rate_limit_key(model=model)
        timestamp = datetime.now(tz=timezone.utc).timestamp()
        with self._lock:
            self._record_request_locked(accounting_key=accounting_key, tokens=tokens, timestamp=timestamp)
        logger.info(
            "Recorded model-aware rate-limit usage event: model=%s, accounting_key=%s, tokens=%s, timestamp=%s.",
            model,
            accounting_key,
            tokens,
            timestamp,
        )

    def _record_request_for_bucket(self, bucket: str, tokens: int) -> None:
        """Record a successful request for an explicit accounting bucket.

        Args:
            bucket: Accounting bucket name used for compatibility or scoped state.
            tokens: Actual or estimated token usage to record.
        """

        accounting_key = self._resolve_rate_limit_key(model=bucket)
        timestamp = datetime.now(tz=timezone.utc).timestamp()
        with self._lock:
            self._record_request_locked(accounting_key=accounting_key, tokens=tokens, timestamp=timestamp)
        logger.info(
            "Recorded legacy/global fallback rate-limit usage event: bucket=%s, accounting_key=%s, tokens=%s, timestamp=%s.",
            bucket,
            accounting_key,
            tokens,
            timestamp,
        )

    def _compute_wait_deadline(self, wait_timeout_seconds: float | None) -> float | None:
        """Compute the absolute deadline for a wait attempt.

        Args:
            wait_timeout_seconds: Maximum time to wait for budget, in seconds.

        Returns:
            The absolute monotonic deadline, or None if waiting is unbounded.
        """

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
        """Check whether waiting for budget has timed out.

        Args:
            deadline: Absolute monotonic deadline for the wait attempt.
            model: Model identifier for the request.
            estimated_tokens: Estimated token usage for the request.
            wait_timeout_seconds: Maximum time to wait for budget, in seconds.

        Returns:
            True if the wait has timed out, otherwise False.
        """

        if deadline is not None and time.monotonic() >= deadline:
            logger.info(
                "Rate limit wait timed out for model=%s: estimated_tokens=%s, wait_timeout_seconds=%s.",
                model,
                estimated_tokens,
                wait_timeout_seconds,
            )
            return True
        return False

    def _build_rate_limit_snapshot_locked(
        self,
        model: str,
        accounting_key: str,
    ) -> _RateLimitSnapshot:
        """Collect usage and resolved limits under the active lock.

        Args:
            model: Model identifier for the request.
            accounting_key: Accounting key used to scope state and logging.

        Returns:
            A snapshot containing usage counts and resolved limits.
        """

        current_tokens, current_requests = self._current_usage_snapshot_locked(accounting_key=accounting_key)
        tpm_limit = self._resolve_tpm_limit(model=model, accounting_key=accounting_key)
        rpm_limit = self._resolve_rpm_limit(model=model, accounting_key=accounting_key)
        return _RateLimitSnapshot(
            current_tokens=current_tokens,
            current_requests=current_requests,
            tpm_limit=tpm_limit,
            rpm_limit=rpm_limit,
        )

    def _resolve_rate_limit_key(self, model: str) -> str:
        """Resolve the accounting key for model-scoped state.

        Args:
            model: Model identifier for the request.

        Returns:
            The normalized accounting key for the model.
        """

        normalized_model = str(model)
        logger.info(
            "Resolved rate-limit accounting key: model=%s.",
            normalized_model,
        )
        return normalized_model

    def _record_request_locked(self, accounting_key: str, tokens: int, timestamp: float) -> None:
        """Record a successful request while holding the service lock.

        Args:
            accounting_key: Accounting key used to scope state.
            tokens: Actual or estimated token usage to record.
            timestamp: UTC timestamp for the request event.
        """

        self._purge_old_events_locked(accounting_key)
        self._usage_events.setdefault(accounting_key, deque()).append(
            _UsageEvent(timestamp=timestamp, tokens=max(tokens, 0))
        )
        self._request_count_events.setdefault(accounting_key, deque()).append(timestamp)

    def _resolve_tpm_limit(self, model: str, accounting_key: str) -> int:
        """Resolve the active TPM limit for a model.

        Args:
            model: Model identifier for the request.
            accounting_key: Accounting key used to scope state and logging.

        Returns:
            A validated token-per-minute limit.
        """

        limit = self._get_tpm_limit(model)
        if limit is None:
            limit = 1
            logger.info(
                "No TPM limit configured for model=%s; using fallback=%s.",
                model,
                limit,
            )
        self._validate_positive_limit(limit=limit, limit_name="TPM", model=model, accounting_key=accounting_key)
        logger.info(
            "Resolved TPM limit for model=%s: %s.",
            model,
            limit,
        )
        return limit

    def _resolve_rpm_limit(self, model: str, accounting_key: str) -> int | None:
        """Resolve the active RPM limit for a model.

        Args:
            model: Model identifier for the request.
            accounting_key: Accounting key used to scope state and logging.

        Returns:
            A validated request-per-minute limit, or None if RPM is disabled.
        """

        limit = self._get_rpm_limit(model)
        if limit is None:
            logger.info(
                "RPM limit is disabled for model=%s because no limit was configured.",
                model,
            )
            return None
        self._validate_positive_limit(limit=limit, limit_name="RPM", model=model, accounting_key=accounting_key)
        logger.info(
            "Resolved RPM limit for model=%s: %s.",
            model,
            limit,
        )
        return limit

    def _get_tpm_limit(self, model: str) -> int | None:
        """Return the current TPM limit.

        Args:
            model: Model identifier for the request.

        Returns:
            The token-per-minute limit for the configured model, or None if unavailable.
        """

        limit = self._config_service.get_model_tpm_limit(model)
        if limit is None:
            logger.info("No TPM limit configured for model=%s.", model)
            return None
        return int(limit)

    def _get_rpm_limit(self, model: str) -> int | None:
        """Return the current RPM limit.

        Args:
            model: Model identifier for the request.

        Returns:
            The request-per-minute limit for the configured model, or None if unavailable.
        """

        limit = self._config_service.get_model_rpm_limit(model)
        if limit is None:
            logger.info("No RPM limit configured for model=%s.", model)
            return None
        return int(limit)

    def _validate_positive_limit(
        self,
        *,
        limit: int,
        limit_name: str,
        model: str,
        accounting_key: str,
    ) -> None:
        """Validate that a resolved limit is a positive integer.

        Args:
            limit: The resolved limit to validate.
            limit_name: Human-readable limit label for logging.
            model: Model identifier for the request.
            accounting_key: Accounting key used to scope state and logging.

        Raises:
            ValueError: If the limit is not a positive integer.
        """

        if int(limit) <= 0:
            logger.error(
                "Invalid %s configured for model=%s: %s.",
                limit_name,
                model,
                limit,
            )
            raise ValueError(f"Invalid {limit_name} configured for model={model!r}: {limit!r}.")

    def _current_usage_snapshot_locked(
        self,
        accounting_key: str,
    ) -> tuple[int, int]:
        """Return the current token and request usage under the active lock.

        Args:
            accounting_key: Accounting key used to scope state.

        Returns:
            A tuple containing the current token total and request count.
        """

        usage_events = self._usage_events.setdefault(accounting_key, deque())
        request_events = self._request_count_events.setdefault(accounting_key, deque())
        current_tokens = sum(event.tokens for event in usage_events)
        current_requests = len(request_events)
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
        if snapshot.rpm_limit is not None:
            request_total = snapshot.current_requests + 1
            if request_total > snapshot.rpm_limit:
                logger.warning(
                    "RPM limit exceeded: current_requests=%s, rpm_limit=%s",
                    snapshot.current_requests,
                    snapshot.rpm_limit,
                )
                return False
        return True

    def _purge_old_events_locked(self, accounting_key: str) -> None:
        """Drop usage events older than the rolling window.

        Args:
            accounting_key: Accounting key used to scope state.
        """

        cutoff = datetime.now(tz=timezone.utc).timestamp() - self._window_seconds
        usage_events = self._usage_events.setdefault(accounting_key, deque())
        request_events = self._request_count_events.setdefault(accounting_key, deque())
        while usage_events and usage_events[0].timestamp < cutoff:
            usage_events.popleft()
        while request_events and request_events[0] < cutoff:
            request_events.popleft()
