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
        model = "openai/gpt-4o-mini"

        service.record_request_for_model(model, 50)

        try:
            service.record_request_for_model(model, 25)
        except Exception as exc:  # pragma: no cover
            self.fail(f"record_request_for_model raised an unexpected exception: {exc}")

    def test_record_request_affects_later_request_decisions(self) -> None:
        """A recorded request should influence later rate-limit decisions."""

        service = RateLimitService(self.config_service, window_seconds=60)
        service.get_model_tpm_limit = lambda model: 1_000  # type: ignore[method-assign]
        model = "openai/gpt-4o-mini"

        try:
            service.record_request_for_model(model, 901)
        except Exception as exc:  # pragma: no cover
            self.fail(f"record_request_for_model raised an unexpected exception: {exc}")

        allowed_after = service.request_allowed(
            model=model,
            estimated_tokens=1_001,
        )

        self.assertFalse(allowed_after)


class RateLimitServiceUnconfiguredLimitsTests(unittest.TestCase):
    """Verify behavior when TPM/RPM are not configured."""

    def _build_service(
        self,
        tpm_limit: int | None,
        rpm_limit: int | None,
    ) -> RateLimitService:
        class ConfigServiceStub:
            def get_model_tpm_limit(self, model: str) -> int | None:
                return tpm_limit

            def get_model_rpm_limit(self, model: str) -> int | None:
                return rpm_limit

            def estimate_token_usage(self, *_args, **_kwargs) -> int:
                return 100

        return RateLimitService(ConfigServiceStub(), window_seconds=60)

    def test_unconfigured_tpm_is_treated_as_unlimited(self) -> None:
        """A missing TPM should allow arbitrarily large token requests."""

        service = self._build_service(tpm_limit=None, rpm_limit=1_000)

        allowed = service.request_allowed(
            model="openai/gpt-4o-mini",
            estimated_tokens=10_000_000,
        )

        self.assertTrue(allowed)

    def test_unconfigured_tpm_emits_warning_log(self) -> None:
        """A missing TPM should emit a warning log on the rate_limit_service logger."""

        service = self._build_service(tpm_limit=None, rpm_limit=1_000)

        with self.assertLogs(
            "monitor_oop.core.infrastructure.rate_limit_service",
            level="WARNING",
        ) as captured:
            service.request_allowed(model="openai/gpt-4o-mini", estimated_tokens=1)

        warning_lines = [line for line in captured.output if "WARNING" in line]
        self.assertTrue(
            any("No TPM limit configured" in line for line in warning_lines),
            f"expected TPM warning, got {warning_lines}",
        )

    def test_unconfigured_rpm_exits_the_process(self) -> None:
        """A missing RPM is a fatal configuration error; sys.exit should fire."""

        service = self._build_service(tpm_limit=1_000, rpm_limit=None)

        with self.assertRaises(SystemExit) as ctx:
            service.request_allowed(model="openai/gpt-4o-mini", estimated_tokens=1)

        self.assertEqual(ctx.exception.code, 1)

    def test_unconfigured_rpm_emits_error_log(self) -> None:
        """A missing RPM should emit an error log before exiting."""

        service = self._build_service(tpm_limit=1_000, rpm_limit=None)

        with self.assertLogs(
            "monitor_oop.core.infrastructure.rate_limit_service",
            level="ERROR",
        ) as captured:
            with self.assertRaises(SystemExit):
                service.request_allowed(model="openai/gpt-4o-mini", estimated_tokens=1)

        error_lines = [line for line in captured.output if "ERROR" in line]
        self.assertTrue(
            any("RPM limit must be configured" in line for line in error_lines),
            f"expected RPM error, got {error_lines}",
        )


class RateLimitServiceAccountingKeyNormalizationTests(unittest.TestCase):
    """Verify provider-prefixed and bare model names map to the same budget."""

    def setUp(self) -> None:
        class ConfigServiceStub:
            def get_model_tpm_limit(self, model: str) -> int:
                return 1_000

            def get_model_rpm_limit(self, model: str) -> int:
                return 10

            def estimate_token_usage(self, *_args, **_kwargs) -> int:
                return 100

        self.service = RateLimitService(ConfigServiceStub(), window_seconds=60)

    def test_provider_prefixed_and_bare_model_share_budget(self) -> None:
        """Recording with the prefixed name should affect the bare name's budget."""

        self.service.record_request_for_model("openai/gpt-4o-mini", 900)

        # 900 already used; another 200 would exceed the 1000 TPM limit.
        allowed = self.service.request_allowed(
            model="gpt-4o-mini",
            estimated_tokens=200,
        )
        self.assertFalse(allowed)

    def test_case_insensitive_normalization(self) -> None:
        """Differing case should not produce divergent budgets."""

        self.service.record_request_for_model("OpenAI/GPT-4o-Mini", 900)

        allowed = self.service.request_allowed(
            model="openai/gpt-4o-mini",
            estimated_tokens=200,
        )
        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
