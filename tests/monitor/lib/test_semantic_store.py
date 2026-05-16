
import unittest
from unittest.mock import MagicMock, patch

from monitor.lib.semantic_store import SemanticStore

class TestSemanticStore(unittest.TestCase):
    def setUp(self):
        # Dummy redis-like saver to track calls
        self.saved = {}
        def mock_save_to_memory(key, value):
            print(f"mock_save_to_memory called with key={key}, value={value}")  # Diagnostic print
            self.saved[key] = value
            return True
        def mock_update_memory(*a, **k):
            return True

        self.tools = {
            "save_to_memory": mock_save_to_memory,
            "update_memory": mock_update_memory,
        }
        self.openai_api_key = "test-key"

        self.store = SemanticStore(
            tools=self.tools,
            openai_api_key=self.openai_api_key,
            system_prompt="Test memory agent system prompt"
        )

    @patch("monitor.lib.semantic_store.litellm.completion")
    def test_store_remembers_when_expected(self, mock_completion):
        # Arrange: Mock LLM returns a 'remember' object
        print(f"ID of self.store.process: {id(self.store.process)}")
        print(f"ID of SemanticStore.process: {id(SemanticStore.process)}")
        mock_completion.return_value = {
            'choices': [{
                'message': {'content': '{"to_remember": "foo", "key": "bar"}'}
            }]
        }
        user_prompt = "Remember this important fact."
        result = self.store.process(user_prompt)
        print(f"self.saved after process: {self.saved}")
        print(f"Result of self.store.process(user_prompt): {result}")

        # Assert the key was saved
        self.assertTrue(result)
        self.assertIn("bar", self.saved)
        self.assertEqual(self.saved["bar"], "foo")

    @patch("monitor.lib.semantic_store.litellm.completion")
    def test_store_handles_nothing_to_remember(self, mock_completion):
        # Arrange: Mock LLM returns a JSON null
        mock_completion.return_value = {
            'choices': [{
                'message': {'content': 'null'}
            }]
        }
        user_prompt = "Nothing important."
        result = self.store.process(user_prompt)
        # Assert nothing got saved
        self.assertIsNone(result)
        self.assertEqual(self.saved, {})

    @patch("monitor.lib.semantic_store.litellm.completion")
    def test_store_handles_llm_and_parsing_errors(self, mock_completion):
        # LLM raises error
        mock_completion.side_effect = Exception("LLM down")
        user_prompt = "Some input"
        result = self.store.process(user_prompt)
        self.assertIsNone(result)

        # LLM returns bad JSON
        mock_completion.side_effect = None
        mock_completion.return_value = {
            'choices': [{
                'message': {'content': 'INVALID_JSON'}
            }]
        }
        result = self.store.process(user_prompt)
        self.assertIsNone(result)

if __name__ == "__main__":
    unittest.main()


