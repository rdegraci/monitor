"""Tests for rate limiting behavior in Monitor OOP."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from monitor_oop.core.infrastructure.rate_limit_service import RateLimitService


class RateLimitServiceTests(unittest.TestCase):
    """Verify rate-limit checks remain stable and non-brittle."""

    def setUp(self) -> None:
        """Create a rate limit service with a mocked config dependency."""

        self.config_service = MagicMock()
        self.config_service.get_model_tpm_limit.return_value = 1_000
        self.config_service.get_model_rpm_limit.return_value = 2
        self.config_service.estimate_token_usage.return_value = 100
        self.service = RateLimitService(self.config_service, window_seconds=60)

    def test_estimate_token_usage_returns_configured_estimate(self) -> None:
        """The estimator should delegate to the config service and return a positive value."""

        estimated_tokens = self.service.estimate_token_usage(
            model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
            previous_response_id=None,
        )

        self.assertEqual(estimated_tokens, 100)

    def test_request_allowed_when_within_limits(self) -> None:
        """A small request should be allowed within the configured budget."""

        allowed = self.service.request_allowed(
            model="openai/gpt-4o-mini",
            estimated_tokens=100,
        )

        self.assertTrue(allowed)

    def test_request_not_allowed_when_tpm_exceeded(self) -> None:
        """A request that exceeds TPM should be rejected."""

        allowed = self.service.request_allowed(
            model="openai/gpt-4o-mini",
            estimated_tokens=1_001,
        )

        self.assertFalse(allowed)

    def test_request_not_allowed_when_rpm_exceeded(self) -> None:
        """A request that exceeds RPM should be rejected."""

        self.service.record_request(50)
        self.service.record_request(50)

        allowed = self.service.request_allowed(
            model="openai/gpt-4o-mini",
            estimated_tokens=10,
        )

        self.assertFalse(allowed)

    def test_record_request_updates_rolling_state(self) -> None:
        """A recorded request should contribute to future rate-limit decisions."""

        self.service.record_request(900)

        allowed = self.service.request_allowed(
            model="openai/gpt-4o-mini",
            estimated_tokens=200,
        )

        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
