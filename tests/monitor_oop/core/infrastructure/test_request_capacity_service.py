"""Tests for request capacity behavior in Monitor OOP."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from monitor_oop.core.infrastructure.request_capacity_service import RequestCapacityService


class RequestCapacityServiceTests(unittest.TestCase):
    """Verify request capacity checks remain stable and non-brittle."""

    def setUp(self) -> None:
        """Create a capacity service with a mocked config dependency."""

        self.config_service = MagicMock()
        self.config_service.get_context_window.return_value = 1_000
        self.config_service.get_output_window.return_value = 200
        self.service = RequestCapacityService(self.config_service)

    def test_request_fits_when_estimate_is_well_within_window(self) -> None:
        """A small request should fit the configured context window."""

        fits = self.service.request_fits(
            model="openai/gpt-4o-mini",
            input_messages=[{"role": "user", "content": "hello"}],
            tools=[],
            previous_response_id=None,
            estimated_input_tokens=100,
        )

        self.assertTrue(fits)

    def test_request_does_not_fit_when_estimate_is_clearly_too_large(self) -> None:
        """A clearly oversized request should fail capacity checks."""

        fits = self.service.request_fits(
            model="openai/gpt-4o-mini",
            input_messages=[{"role": "user", "content": "x" * 10}],
            tools=[],
            previous_response_id=None,
            estimated_input_tokens=10_000,
        )

        self.assertFalse(fits)

    def test_evaluate_request_returns_structured_result_for_fitting_request(self) -> None:
        """A fitting request should return structured capacity details."""

        result = self.service.evaluate_request(
            model="openai/gpt-4o-mini",
            input_messages=[{"role": "user", "content": "hello"}],
            tools=[],
            previous_response_id=None,
            estimated_input_tokens=100,
        )

        self.assertTrue(result.fits)
        self.assertGreater(result.context_window, 0)
        self.assertGreater(result.output_window, 0)
        self.assertGreater(result.completion_headroom, 0)
        self.assertIsNone(result.reason)

    def test_evaluate_request_returns_reason_when_it_does_not_fit(self) -> None:
        """A failed capacity check should include a readable reason."""

        result = self.service.evaluate_request(
            model="openai/gpt-4o-mini",
            input_messages=[{"role": "user", "content": "x" * 10}],
            tools=[],
            previous_response_id=None,
            estimated_input_tokens=10_000,
        )

        self.assertFalse(result.fits)
        self.assertIsNotNone(result.reason)
        self.assertIn("context window", result.reason or "")


if __name__ == "__main__":
    unittest.main()
