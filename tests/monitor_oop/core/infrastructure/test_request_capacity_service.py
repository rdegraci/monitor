"""Tests for request capacity behavior in Monitor OOP."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.infrastructure.rate_limit_service import RateLimitService
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


class EstimatorConsistencyTests(unittest.TestCase):
    """Lock in that capacity and rate-limit preflights agree on token estimates."""

    def test_capacity_and_rate_limit_preflights_produce_same_estimate(self) -> None:
        """Both preflights must delegate to the same canonical estimator.

        Previously each service maintained its own formula and could disagree
        materially on the same input. The capacity preflight now delegates to
        ``ConfigService.estimate_token_usage`` — the same path the rate-limit
        preflight uses — so both gates evaluate identical numbers.
        """

        config_service = ConfigService()
        capacity_service = RequestCapacityService(config_service)
        rate_limit_service = RateLimitService(config_service)

        messages: list[dict[str, object]] = [
            {"role": "system", "content": "you are a helpful assistant"},
            {"role": "user", "content": "what is the weather in San Diego?"},
            {
                "role": "assistant",
                "content": "calling tool",
                "tool_calls": [
                    {"id": "call_1", "name": "get_weather", "arguments": "{}"}
                ],
            },
            {
                "role": "tool",
                "content": "sunny",
                "tool_call_id": "call_1",
                "name": "get_weather",
            },
            {"role": "assistant", "content": "it is sunny in San Diego"},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "get the weather for a location",
                    "parameters": {"type": "object"},
                },
            }
        ]

        capacity_result = capacity_service.evaluate_request(
            model="openai/gpt-4o",
            input_messages=messages,
            tools=tools,
            previous_response_id=None,
        )
        rate_limit_estimate = rate_limit_service.estimate_token_usage(
            model="openai/gpt-4o",
            messages=messages,
            tools=tools,
            previous_response_id=None,
        )

        self.assertEqual(
            capacity_result.estimated_input_tokens,
            rate_limit_estimate,
            msg=(
                "Capacity and rate-limit preflights must produce the same token "
                "estimate for identical inputs."
            ),
        )


if __name__ == "__main__":
    unittest.main()
