
import unittest
from unittest.mock import patch, MagicMock

import monitor.core.tooling as tooling

class TestTooling(unittest.TestCase):
    def test_parse_function_args_dict(self):
        data = {"foo": 1}
        self.assertEqual(tooling.parse_function_args(data), data)

    def test_parse_function_args_json(self):
        args_str = '{"foo": 42}'
        self.assertEqual(tooling.parse_function_args(args_str), {"foo": 42})

    def test_parse_function_args_invalid_json(self):
        with self.assertRaises(Exception):
            tooling.parse_function_args('{bad')

    def test_create_tool_result_message(self):
        msg = tooling.create_tool_result_message("result", None, "id123")
        self.assertEqual(msg, {'role': 'tool', 'content': 'result', 'tool_call_id': 'id123'})

        error_msg = tooling.create_tool_result_message(None, "error!", "idX")
        self.assertEqual(error_msg, {'role': 'tool', 'content': 'error!', 'tool_call_id': 'idX'})

    @patch("monitor.core.tooling.AVAILABLE_TOOLS", new_callable=lambda: {"foo": lambda x: x + 1})
    @patch("monitor.core.tooling.count_message_tokens", return_value=1)
    @patch("monitor.lib.rate_limiter.RATE_LIMITER")
    def test_execute_tool_call_success(self, mock_limiter, mock_token_count, mock_available):
        tool_call = {
            "function": {
                "arguments": '{"x": 2}',
                "name": "foo"
            }
        }
        with patch.dict(tooling.AVAILABLE_TOOLS, {"foo": lambda x: x + 1}):
            result, err = tooling.execute_tool_call(tool_call)
            self.assertEqual(result, 3)
            self.assertIsNone(err)

    @patch("monitor.core.tooling.AVAILABLE_TOOLS", new_callable=dict)
    def test_execute_tool_call_missing(self, mock_available):
        tool_call = {
            "function": {"arguments": '{}', "name": "notfound"}
        }
        result, err = tooling.execute_tool_call(tool_call)
        self.assertIsNone(result)
        self.assertIn("not found in available_functions", err)

if __name__ == "__main__":
    unittest.main()


