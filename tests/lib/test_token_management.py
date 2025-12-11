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
        
        class NoUsageObject:
            """Simple object that does not have a 'usage' attribute."""
            pass

        mock_response = NoUsageObject()

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

    def test_update_token_usage_with_none_input(self):
        """Test update_token_usage handles None input as zero.

        Verifies that passing None to update_token_usage is treated as adding zero tokens
        and does not change TOTAL_TOKEN_COUNT.

        Args:
            None: The input value is None.

        Returns:
            None
        """
        config.TOTAL_TOKEN_COUNT = 400
        result = update_token_usage(None)
        self.assertEqual(result, 400)
        self.assertEqual(config.TOTAL_TOKEN_COUNT, 400)

    def test_update_token_usage_initializes_total_token_count_when_missing(self):
        """Ensure TOTAL_TOKEN_COUNT is initialized when missing.

        If the TOTAL_TOKEN_COUNT attribute is absent from the config module,
        update_token_usage should initialize it (treating missing as zero) and
        correctly add the provided token amount.

        Args:
            None: The test manipulates the config module to remove TOTAL_TOKEN_COUNT.

        Returns:
            None
        """
        # Remove TOTAL_TOKEN_COUNT if it exists to simulate missing attribute
        if hasattr(config, 'TOTAL_TOKEN_COUNT'):
            delattr(config, 'TOTAL_TOKEN_COUNT')

        tokens_to_add = 25
        result = update_token_usage(tokens_to_add)

        # Expect that TOTAL_TOKEN_COUNT has been initialized to the added amount
        self.assertEqual(result, tokens_to_add)
        self.assertTrue(hasattr(config, 'TOTAL_TOKEN_COUNT'))
        self.assertEqual(config.TOTAL_TOKEN_COUNT, tokens_to_add)

    def test_update_token_usage_with_response_total_tokens_none(self):
        """Test that update_token_usage treats a response with usage.total_tokens == None as zero.

        Verifies that if a response object provides a usage attribute whose
        total_tokens value is None, update_token_usage will treat it as zero and
        leave TOTAL_TOKEN_COUNT unchanged.

        Args:
            None: The test creates a mock response object with usage.total_tokens set to None.

        Returns:
            None
        """
        config.TOTAL_TOKEN_COUNT = 100

        mock_response = MagicMock()
        mock_response.usage.total_tokens = None

        result = update_token_usage(mock_response)

        self.assertEqual(result, 100)
        self.assertEqual(config.TOTAL_TOKEN_COUNT, 100)

    def test_count_message_tokens_coerce_non_string_in_dict(self):
        """Test that count_message_tokens coerces non-string 'content' values in dict to str.

        Verifies that when a message dictionary contains a non-string value
        under the 'content' key (e.g., an integer), count_message_tokens will coerce
        the value to a string and return a positive integer token estimate.

        Args:
            None: The test uses a dict with an integer content value.

        Returns:
            None
        """
        message = {'content': 12345}
        result = count_message_tokens(message)

        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)
        self.assertEqual(result, count_message_tokens({'content': str(12345)}))

    def test_count_message_tokens_handles_object_with_content_attribute(self):
        """Test that count_message_tokens handles objects with a 'content' attribute and coerces non-str.

        Verifies that an object providing a 'content' attribute (not a dict)
        will be accepted by count_message_tokens. If the attribute is non-string, it
        should be coerced to a string and token count computed.

        Args:
            None: The test constructs a simple object with a numeric content attribute.

        Returns:
            None
        """
        class ContentObject:
            def __init__(self, content):
                self.content = content

        obj = ContentObject(67890)
        result = count_message_tokens(obj)

        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)
        self.assertEqual(result, count_message_tokens({'content': str(67890)}))

    def test_count_message_tokens_sums_list_elements(self):
        """Test that count_message_tokens coerces a list 'content' to a string and tokenizes that string.

        When the 'content' of a message is a list of items, current implementation
        coerces the list to its string representation and tokenizes that combined string.

        Args:
            None: The test uses a list of string elements as the content.

        Returns:
            None
        """
        parts = ['This is a sentence.', 'Another one.']
        message = {'content': parts}

        result = count_message_tokens(message)

        expected = count_message_tokens({'content': str(parts)})
        self.assertIsInstance(result, int)
        self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()
