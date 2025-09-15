import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

import monitor.core.tools as tools


class TestCoreTools(unittest.TestCase):
    """Covers src/monitor/core/tools.configure_tools behavior."""

    def setUp(self):
        # Fresh mutable containers per test to avoid global side effects
        self.tool_desc = [
            {"type": "function", "function": {"name": "alpha"}},
            {"type": "function", "function": {"name": "beta"}},
            {"type": "function", "function": {}},  # missing name -> warning path
            {"type": "function"},  # missing function key -> warning path
        ]
        self.gemini_desc = []
        self.state = {}

    @patch.object(tools, "logger")
    @patch.object(tools, "add_openai_editor_tools")
    @patch.object(tools, "remove_text_file_editor_tools")
    @patch.object(tools, "remove_openai_editor_tools")
    @patch.object(tools, "add_text_file_editor_tools")
    @patch.object(tools, "add_memory_tools")
    @patch.object(tools, "add_weather_tools")
    @patch.object(tools, "get_first_segment")
    @patch.object(tools, "GEMINI_TOOL_DESCRIPTIONS", new_callable=list)
    @patch.object(tools, "TOOL_DESCRIPTIONS", new_callable=list)
    @patch.object(tools, "TOOL_STATE", new_callable=dict)
    def test_configure_tools_openai_branch(
        self,
        mock_state,
        mock_tool_desc,
        mock_gemini_desc,
        mock_get_first_segment,
        mock_add_weather,
        mock_add_memory,
        mock_add_text_editor,
        mock_remove_openai_editors,
        mock_remove_text_editor,
        mock_add_openai_editors,
        mock_logger,
    ):
        """When model is openai, configure openai editors and set tool state for valid entries."""
        # Provide initial tool lists
        mock_tool_desc.extend(self.tool_desc)
        mock_gemini_desc.extend(self.gemini_desc)
        mock_get_first_segment.return_value = "openai"

        tools.configure_tools()

        # Weather and memory setup always attempted
        mock_add_weather.assert_called_once()
        mock_add_memory.assert_called_once()

        # For openai branch
        mock_remove_text_editor.assert_called_once()
        mock_add_openai_editors.assert_called_once()
        mock_add_text_editor.assert_not_called()
        mock_remove_openai_editors.assert_not_called()

        # TOOL_STATE should be marked True for valid names
        self.assertIs(True, mock_state.get("alpha"))
        self.assertIs(True, mock_state.get("beta"))
        # Missing names should not be present
        self.assertNotIn("", mock_state)
        # Warning should be logged at least for the items missing a name
        self.assertTrue(mock_logger.warning.called)

    @patch.object(tools, "logger")
    @patch.object(tools, "add_openai_editor_tools")
    @patch.object(tools, "remove_text_file_editor_tools")
    @patch.object(tools, "remove_openai_editor_tools")
    @patch.object(tools, "add_text_file_editor_tools")
    @patch.object(tools, "add_memory_tools")
    @patch.object(tools, "add_weather_tools")
    @patch.object(tools, "get_first_segment")
    @patch.object(tools, "GEMINI_TOOL_DESCRIPTIONS", new_callable=list)
    @patch.object(tools, "TOOL_DESCRIPTIONS", new_callable=list)
    @patch.object(tools, "TOOL_STATE", new_callable=dict)
    def test_configure_tools_anthropic_branch(
        self,
        mock_state,
        mock_tool_desc,
        mock_gemini_desc,
        mock_get_first_segment,
        mock_add_weather,
        mock_add_memory,
        mock_add_text_editor,
        mock_remove_openai_editors,
        mock_remove_text_editor,
        mock_add_openai_editors,
        mock_logger,
    ):
        """When model is anthropic, configure anthropic text editor tools and set state."""
        mock_tool_desc.extend(self.tool_desc)
        mock_gemini_desc.extend(self.gemini_desc)
        mock_get_first_segment.return_value = "anthropic"

        tools.configure_tools()

        # Weather and memory setup always attempted
        mock_add_weather.assert_called_once()
        mock_add_memory.assert_called_once()

        # For anthropic branch
        mock_add_text_editor.assert_called_once()
        mock_remove_openai_editors.assert_called_once()
        mock_remove_text_editor.assert_not_called()
        mock_add_openai_editors.assert_not_called()

        # TOOL_STATE should be marked True for valid names
        self.assertIs(True, mock_state.get("alpha"))
        self.assertIs(True, mock_state.get("beta"))
        # Warning should be logged for missing tool name entries
        self.assertTrue(mock_logger.warning.called)


if __name__ == "__main__":
    unittest.main()
