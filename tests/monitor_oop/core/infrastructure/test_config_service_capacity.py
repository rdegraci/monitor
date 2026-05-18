"""Tests for configuration accessors used by capacity and rate limiting."""
from __future__ import annotations

import unittest

from monitor_oop.core.config_service import ConfigService


class ConfigServiceCapacityTests(unittest.TestCase):
    """Verify the configuration service exposes stable capacity helpers."""

    def setUp(self) -> None:
        """Create a configuration service for testing."""

        self.service = ConfigService()

    def test_context_window_accessor_returns_positive_value(self) -> None:
        """The context window accessor should return a positive integer."""

        self.assertGreater(self.service.get_context_window(), 0)

    def test_output_window_accessor_returns_positive_value(self) -> None:
        """The output window accessor should return a positive integer."""

        self.assertGreater(self.service.get_output_window(), 0)

    def test_model_tpm_limit_accessor_returns_none_when_unconfigured(self) -> None:
        """The TPM accessor returns None when no TPM is configured (treated as unlimited)."""

        self.assertIsNone(self.service.get_model_tpm_limit())

    def test_model_rpm_limit_accessor_returns_none_when_unconfigured(self) -> None:
        """The RPM accessor returns None when no RPM is configured (fatal at runtime)."""

        self.assertIsNone(self.service.get_model_rpm_limit())


if __name__ == "__main__":
    unittest.main()
