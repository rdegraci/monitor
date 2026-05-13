"""Tests for LLM response client preflight behavior in Monitor OOP."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.infrastructure.llm_response_client import LLMResponseClient
from monitor_oop.core.infrastructure.rate_limit_service import RateLimitService
from monitor_oop.core.infrastructure.request_capacity_service import RequestCapacityService


class LLMResponseClientPreflightTests(unittest.TestCase):
    """Verify the response client checks capacity and rate limits before dispatch."""

    def setUp(self) -> None:
        """Create a response client with mocked dependencies."""

        self.config_service = MagicMock(spec=ConfigService)
        self.config_service.get_openai_api_key.return_value = "test-key"
        self.config_service.get_model.return_value = "openai/gpt-4o-mini"
        self.adapter = MagicMock()
        self.adapter.complete.return_value = {"id": "resp_1", "output": []}
        self.tool_service = MagicMock()
        self.tool_service.build_responses_tools.return_value = []
        self.capacity_service = MagicMock(spec=RequestCapacityService)
        self.capacity_service.request_fits.return_value = True
        self.rate_limit_service = MagicMock(spec=RateLimitService)
        self.rate_limit_service.estimate_token_usage.return_value = 25
        self.rate_limit_service.request_allowed.return_value = True
        self.client = LLMResponseClient(
            self.config_service,
            self.adapter,
            self.tool_service,
            self.capacity_service,
            self.rate_limit_service,
        )

    def test_capacity_check_runs_before_rate_limit_check(self) -> None:
        """The client should check fit before rate limiting."""

        self.client.create_response(
            [{"role": "user", "content": "hello"}],
            previous_response_id=None,
        )

        self.capacity_service.request_fits.assert_called_once()
        self.rate_limit_service.estimate_token_usage.assert_called_once()
        self.rate_limit_service.request_allowed.assert_called_once()
        self.adapter.complete.assert_called_once()

    def test_adapter_not_called_when_capacity_fails(self) -> None:
        """Requests that do not fit must fail before adapter dispatch."""

        self.capacity_service.request_fits.return_value = False

        with self.assertRaises(ValueError):
            self.client.create_response(
                [{"role": "user", "content": "hello"}],
                previous_response_id=None,
            )

        self.adapter.complete.assert_not_called()
        self.rate_limit_service.estimate_token_usage.assert_not_called()
        self.rate_limit_service.request_allowed.assert_not_called()

    def test_adapter_not_called_when_rate_limit_denies_request(self) -> None:
        """Requests denied by rate limiting must not reach the adapter."""

        self.rate_limit_service.request_allowed.return_value = False

        with self.assertRaises(ValueError):
            self.client.create_response(
                [{"role": "user", "content": "hello"}],
                previous_response_id=None,
            )

        self.capacity_service.request_fits.assert_called_once()
        self.rate_limit_service.estimate_token_usage.assert_called_once()
        self.rate_limit_service.request_allowed.assert_called_once()
        self.adapter.complete.assert_not_called()

    def test_adapter_called_when_all_preflight_checks_pass(self) -> None:
        """Requests that pass all checks should reach the adapter."""

        response = self.client.create_response(
            [{"role": "user", "content": "hello"}],
            previous_response_id=None,
        )

        self.assertEqual(response, {"id": "resp_1", "output": []})
        self.adapter.complete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
