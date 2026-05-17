"""Tests for rate limiting behavior in Monitor OOP."""
from __future__ import annotations

import unittest

from monitor_oop.core.infrastructure.rate_limit_service import RateLimitService


class RateLimitServiceTests(unittest.TestCase):
    """Verify rate-limit checks remain stable and non-brittle."""

    def setUp(self) -> None:
        """Create a rate limit service with a mocked config dependency."""

        class ConfigServiceStub:
            def __init__(self) -> None:
                self.token_usage = 0
                self.request_count = 0

            def get_model_tpm_limit(self, model: str) -> int:
                return 1_000

            def get_model_rpm_limit(self, model: str) -> int:
                return 2

            def estimate_token_usage(
                self,
                model: str,
                messages: list[dict[str, str]],
                tools: list[dict[str, object]],
                previous_response_id: str | None,
            ) -> int:
                return 100

        self.config_service = ConfigServiceStub()
        self.service = RateLimitService(self.config_service, window_seconds=60)

    def _make_service(self, window_seconds: float) -> RateLimitService:
        """Create a rate limit service with the configured mock dependency."""

        return RateLimitService(self.config_service, window_seconds=window_seconds)

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

        service = RateLimitService(self.config_service, window_seconds=60)
        service.get_model_rpm_limit = lambda model: 1  # type: ignore[method-assign]

        service.record_request(50)

        try:
            service.record_request(25)
        except Exception as exc:  # pragma: no cover
            self.fail(f"record_request raised an unexpected exception: {exc}")

    def test_record_request_affects_later_request_decisions(self) -> None:
        """A recorded request should influence later rate-limit decisions."""

        service = RateLimitService(self.config_service, window_seconds=60)
        service.get_model_tpm_limit = lambda model: 1_000  # type: ignore[method-assign]

        try:
            service.record_request(901)
        except Exception as exc:  # pragma: no cover
            self.fail(f"record_request raised an unexpected exception: {exc}")

        allowed_after = service.request_allowed(
            model="openai/gpt-4o-mini",
            estimated_tokens=1_001,
        )

        self.assertFalse(allowed_after)


if __name__ == "__main__":
    unittest.main()
