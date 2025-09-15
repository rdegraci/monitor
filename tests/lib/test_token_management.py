
"""
Test cases for lib/token_management.py
"""

import unittest
import sys
import os
from unittest.mock import patch, MagicMock

# Add the project root to the path to import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from monitor import config
from monitor.lib.token_management import count_message_tokens, update_token_usage


class TestTokenManagement(unittest.TestCase):
    """Test cases for token management functions."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        # Store original token count to restore after tests
        self.original_token_count = getattr(config, 'TOTAL_TOKEN_COUNT', 0)

    def tearDown(self):
        """Clean up after each test method."""
        # Restore original token count
        config.TOTAL_TOKEN_COUNT = self.original_token_count

    def test_count_message_tokens_valid_message(self):
        """Test counting tokens for a valid message with content."""
        message = {'content': 'Hello world, how are you doing today?'}
        result = count_message_tokens(message)
        # Should return a positive integer (actual token estimate expected to be > 0)
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    def test_count_message_tokens_empty_content(self):
        """Test counting tokens for a message with empty content."""
        message = {'content': ''}
        result = count_message_tokens(message)
        self.assertEqual(result, 0)

    def test_count_message_tokens_no_content_key(self):
        """Test counting tokens for a message without content key."""
        message = {'role': 'user'}
        result = count_message_tokens(message)
        self.assertEqual(result, 0)

    def test_update_token_usage_with_integer(self):
        """Test updating token usage with an integer value."""
        # Initialize config token count
        config.TOTAL_TOKEN_COUNT = 100
        result = update_token_usage(50)
        self.assertEqual(result, 150)
        self.assertEqual(config.TOTAL_TOKEN_COUNT, 150)

    def test_update_token_usage_with_response_object(self):
        """Test updating token usage with a response object containing usage info."""
        config.TOTAL_TOKEN_COUNT = 200
        
        mock_response = MagicMock()
        mock_response.usage.total_tokens = 75

        result = update_token_usage(mock_response)

        self.assertEqual(result, 275)
        self.assertEqual(config.TOTAL_TOKEN_COUNT, 275)

    def test_update_token_usage_with_invalid_response_object(self):
        """Test updating token usage with a response object without usage info."""
        config.TOTAL_TOKEN_COUNT = 300
        
        mock_response = MagicMock()
        if hasattr(mock_response, 'usage'):
            del mock_response.usage

        result = update_token_usage(mock_response)

        self.assertEqual(result, 300)
        self.assertEqual(config.TOTAL_TOKEN_COUNT, 300)

    def test_update_token_usage_zero_tokens(self):
        """Test updating token usage with zero tokens."""
        config.TOTAL_TOKEN_COUNT = 100
        result = update_token_usage(0)
        self.assertEqual(result, 100)
        self.assertEqual(config.TOTAL_TOKEN_COUNT, 100)

    def test_update_token_usage_negative_tokens(self):
        """Test updating token usage with negative tokens."""
        config.TOTAL_TOKEN_COUNT = 100
        result = update_token_usage(-10)
        self.assertEqual(result, 90)
        self.assertEqual(config.TOTAL_TOKEN_COUNT, 90)

    # @patch('monitor.lib.token_management.logger')
    # def test_update_token_usage_exception_handling(self, mock_logger):
    #     """Test that exceptions during token usage update are handled gracefully."""
    #     # Create a scenario where config access fails completely by patching the config module
    #     with patch('monitor.lib.token_management.config') as mock_config:
    #         # Make accessing TOTAL_TOKEN_COUNT raise an exception
    #         type(mock_config).TOTAL_TOKEN_COUNT = MagicMock(side_effect=Exception("Config error"))
    #         
    #         result = update_token_usage(25)
    #         
    #         # Should return 0 as the final fallback
    #         self.assertEqual(result, 0)
    #         # Should log errors
    #         self.assertGreaterEqual(mock_logger.error.call_count, 1)

    def test_count_message_tokens_integration(self):
        """Integration test for count_message_tokens without mocking estimate_token_count."""
        message = {'content': 'This is a simple test message with several words.'}
        
        result = count_message_tokens(message)
        
        # Should return a positive integer (actual token estimate)
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    def test_update_token_usage_integration(self):
        """Integration test for update_token_usage without mocking."""
        # Set initial token count
        initial_count = 500
        config.TOTAL_TOKEN_COUNT = initial_count
        
        # Add some tokens
        tokens_to_add = 125
        result = update_token_usage(tokens_to_add)
        
        expected_count = initial_count + tokens_to_add
        self.assertEqual(result, expected_count)
        self.assertEqual(config.TOTAL_TOKEN_COUNT, expected_count)


if __name__ == '__main__':
    unittest.main()


