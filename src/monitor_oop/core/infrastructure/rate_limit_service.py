"""Rate limiting helpers for Monitor OOP LLM flows."""
from __future__ import annotations

import logging
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

    def request_allowed(self, model: str, estimated_tokens: int) -> bool:
        """Check whether a request is allowed under the active rate-limit budget.

        Args:
            model: Model identifier for the request.
            estimated_tokens: Estimated token usage for the request.

        Returns:
            True when the request fits within the active budget, otherwise False.
        """

        self._purge_old_events()
        current_tokens = sum(event.tokens for event in self._usage_events)
        current_requests = len(self._request_count_events)
        tpm_limit = self._get_tpm_limit(model)
        rpm_limit = self._get_rpm_limit(model)
        logger.info(
            "Evaluating rate limit for model=%s, estimated_tokens=%s, current_tokens=%s, current_requests=%s, tpm_limit=%s, rpm_limit=%s, window_seconds=%s.",
            model,
            estimated_tokens,
            current_tokens,
            current_requests,
            tpm_limit,
            rpm_limit,
            self._window_seconds,
        )
        token_request_total = current_tokens + estimated_tokens
        token_limit_exceeded = token_request_total > tpm_limit
        if token_limit_exceeded:
            logger.warning(
                "TPM limit exceeded: estimated_tokens=%s, current_tokens=%s, tpm_limit=%s",
                estimated_tokens,
                current_tokens,
                tpm_limit,
            )
            return False
        request_total = current_requests + 1
        request_limit_exceeded = request_total > rpm_limit
        if request_limit_exceeded:
            logger.warning(
                "RPM limit exceeded: current_requests=%s, rpm_limit=%s",
                current_requests,
                rpm_limit,
            )
            return False
        logger.info(
            "Rate limit allowed for model=%s: estimated_tokens=%s, current_tokens=%s, current_requests=%s, tpm_limit=%s, rpm_limit=%s.",
            model,
            estimated_tokens,
            current_tokens,
            current_requests,
            tpm_limit,
            rpm_limit,
        )
        return True

    def record_request(self, tokens: int) -> None:
        """Record a successful request in the rolling accounting window.

        Args:
            tokens: Actual or estimated token usage to record.
        """

        self._purge_old_events()
        timestamp = datetime.now(tz=timezone.utc).timestamp()
        self._usage_events.append(_UsageEvent(timestamp=timestamp, tokens=max(tokens, 0)))
        self._request_count_events.append(timestamp)
        logger.info("Recorded rate-limit usage event: tokens=%s, timestamp=%s.", tokens, timestamp)

    def _get_tpm_limit(self, model: str) -> int:
        """Return the current TPM limit.

        Args:
            model: Model identifier for the request.

        Returns:
            The token-per-minute limit for the configured model.
        """

        limit = self._config_service.get_model_tpm_limit(model)
        if limit is None:
            logger.info(
                "No TPM limit configured for model=%s; falling back to default value 1.",
                model,
            )
            return 1
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
            logger.info(
                "No RPM limit configured for model=%s; falling back to default value 1.",
                model,
            )
            return 1
        logger.info("Resolved RPM limit for model=%s: %s.", model, limit)
        return limit

    def _purge_old_events(self) -> None:
        """Drop usage events older than the rolling window."""

        cutoff = datetime.now(tz=timezone.utc).timestamp() - self._window_seconds
        while self._usage_events and self._usage_events[0].timestamp < cutoff:
            self._usage_events.popleft()
        while self._request_count_events and self._request_count_events[0] < cutoff:
            self._request_count_events.popleft()
