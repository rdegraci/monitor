import unittest
from unittest.mock import Mock, patch
import monitor.core.query_service as qs

class TestQueryService(unittest.TestCase):
    def setUp(self):
        # Attempt to reset the global _query_function before each test
        qs._query_function = None

    def test_query_raises_before_registration(self):
        """Test that query() raises if no function is registered."""
        with self.assertRaises(RuntimeError) as cm, patch("monitor.core.query_service.logger") as mock_logger:
            qs.query("test")
        self.assertIn("Query function not initialized", str(cm.exception))
        mock_logger.error.assert_called_once()

    def test_query_calls_registered_function(self):
        """Test that query() calls the registered function and returns its result."""
        mock_func = Mock(return_value="foo bar")
        qs.register_query_function(mock_func)
        result = qs.query("abc", key="val")
        mock_func.assert_called_once_with("abc", key="val")
        self.assertEqual(result, "foo bar")

    def test_register_is_idempotent(self):
        """Test that register_query_function can be called multiple times."""
        mock_func1 = Mock(return_value="one")
        mock_func2 = Mock(return_value="two")
        qs.register_query_function(mock_func1)
        qs.register_query_function(mock_func2)
        result = qs.query()
        self.assertEqual(result, "two")
        self.assertEqual(mock_func1.call_count, 0)
        self.assertEqual(mock_func2.call_count, 1)

if __name__ == "__main__":
    unittest.main()
