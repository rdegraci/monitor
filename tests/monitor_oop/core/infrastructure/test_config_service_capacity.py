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

    def test_model_tpm_limit_accessor_returns_positive_value(self) -> None:
        """The TPM accessor should return a positive integer fallback."""

        self.assertGreater(self.service.get_model_tpm_limit(), 0)

    def test_model_rpm_limit_accessor_returns_non_negative_value(self) -> None:
        """The RPM accessor should return a non-negative integer fallback."""

        self.assertGreaterEqual(self.service.get_model_rpm_limit(), 0)


if __name__ == "__main__":
    unittest.main()
