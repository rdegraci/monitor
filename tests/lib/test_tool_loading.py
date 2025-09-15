import unittest
from unittest.mock import MagicMock
import monitor.lib.tool_loading as tool_loading

class TestToolLoading(unittest.TestCase):
    def setUp(self):
        # Create clean tool descriptions and state for each test
        self.tool_descriptions = []
        self.gemini_tool_descriptions = []
        self.tool_state = {}

    def test_add_tool_success(self):
        tool_def = {
            "type": "function",
            "function": {
                "name": "mock_tool",
                "description": "A mocked tool",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        }
        added = tool_loading.add_tool(
            self.tool_descriptions,
            self.gemini_tool_descriptions,
            self.tool_state,
            tool_def,
        )
        self.assertTrue(added)
        self.assertIn(tool_def, self.tool_descriptions)
        self.assertIn(tool_def, self.gemini_tool_descriptions)
        self.assertIn("mock_tool", self.tool_state)
        self.assertTrue(self.tool_state["mock_tool"])

    def test_add_tool_duplicate(self):
        tool_def = {
            "type": "function",
            "function": {
                "name": "dup_tool",
                "description": "Desc",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        # Add once
        tool_loading.add_tool(
            self.tool_descriptions,
            self.gemini_tool_descriptions,
            self.tool_state,
            tool_def,
        )
        # Try to add again
        added2 = tool_loading.add_tool(
            self.tool_descriptions,
            self.gemini_tool_descriptions,
            self.tool_state,
            tool_def,
        )
        self.assertFalse(added2)
        self.assertEqual(self.tool_descriptions.count(tool_def), 1)

    def test_remove_tool_success(self):
        tool_def = {
            "type": "function",
            "function": {"name": "remove_me", "description": "", "parameters": {}}
        }
        self.tool_descriptions.append(tool_def)
        self.tool_state["remove_me"] = True
        result = tool_loading.remove_tool(self.tool_descriptions, self.tool_state, "remove_me")
        self.assertTrue(result)
        self.assertNotIn(tool_def, self.tool_descriptions)
        self.assertNotIn("remove_me", self.tool_state)

    def test_remove_tool_unknown(self):
        # Try to remove a tool not in the list
        result = tool_loading.remove_tool(self.tool_descriptions, self.tool_state, "not_found")
        self.assertFalse(result)

    def test_get_first_segment(self):
        self.assertEqual(tool_loading.get_first_segment("anthropic/xxx"), "anthropic")
        self.assertEqual(tool_loading.get_first_segment(""), "")

if __name__ == '__main__':
    unittest.main()
