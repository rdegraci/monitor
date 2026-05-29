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
    @patch.object(tools, "remove_anthropic_native_editor_tools")
    @patch.object(tools, "remove_text_file_neutral_tools")
    @patch.object(tools, "add_anthropic_native_editor_tools")
    @patch.object(tools, "remove_openai_editor_tools")
    @patch.object(tools, "add_text_file_neutral_tools")
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
        mock_add_text_neutral,
        mock_remove_openai_editors,
        mock_add_anthropic_native,
        mock_remove_text_neutral,
        mock_remove_anthropic_native,
        mock_add_openai_editors,
        mock_logger,
    ):
        """openai branch: surgical text_file_* + modify_source_code; strip any Anthropic-native leftovers."""
        mock_tool_desc.extend(self.tool_desc)
        mock_gemini_desc.extend(self.gemini_desc)
        mock_get_first_segment.return_value = "openai"

        tools.configure_tools()

        mock_add_weather.assert_called_once()
        mock_add_memory.assert_called_once()

        mock_add_text_neutral.assert_called_once()
        mock_add_openai_editors.assert_called_once()
        # Anthropic-native declarations are stripped so a runtime switch from
        # an Anthropic model doesn't leave dangling tool entries.
        mock_remove_anthropic_native.assert_called_once()
        # Anthropic native add path not taken; surgical not stripped.
        mock_add_anthropic_native.assert_not_called()
        mock_remove_text_neutral.assert_not_called()
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
    @patch.object(tools, "remove_anthropic_native_editor_tools")
    @patch.object(tools, "remove_text_file_neutral_tools")
    @patch.object(tools, "add_anthropic_native_editor_tools")
    @patch.object(tools, "remove_openai_editor_tools")
    @patch.object(tools, "add_text_file_neutral_tools")
    @patch.object(tools, "add_memory_tools")
    @patch.object(tools, "add_weather_tools")
    @patch.object(tools, "get_first_segment")
    @patch.object(tools, "GEMINI_TOOL_DESCRIPTIONS", new_callable=list)
    @patch.object(tools, "TOOL_DESCRIPTIONS", new_callable=list)
    @patch.object(tools, "TOOL_STATE", new_callable=dict)
    def test_configure_tools_anthropic_branch_with_matching_native(
        self,
        mock_state,
        mock_tool_desc,
        mock_gemini_desc,
        mock_get_first_segment,
        mock_add_weather,
        mock_add_memory,
        mock_add_text_neutral,
        mock_remove_openai_editors,
        mock_add_anthropic_native,
        mock_remove_text_neutral,
        mock_remove_anthropic_native,
        mock_add_openai_editors,
        mock_logger,
    ):
        """Anthropic model WITH a matching native gate: use native only, strip surgical."""
        mock_tool_desc.extend(self.tool_desc)
        mock_gemini_desc.extend(self.gemini_desc)
        mock_get_first_segment.return_value = "anthropic"
        mock_add_anthropic_native.return_value = True  # gate matched

        tools.configure_tools()

        mock_add_weather.assert_called_once()
        mock_add_memory.assert_called_once()

        mock_add_anthropic_native.assert_called_once()
        # Native available → surgical fallback is stripped so the model picks
        # its trained-for native protocol unambiguously.
        mock_remove_text_neutral.assert_called_once()
        mock_add_text_neutral.assert_not_called()
        # OpenAI's modify_source_code stripped.
        mock_remove_openai_editors.assert_called_once()
        mock_add_openai_editors.assert_not_called()
        # Strip-then-add refresh: native is removed first to clear stale `type`
        # from a previous Anthropic-model session before adding the new one.
        mock_remove_anthropic_native.assert_called_once()

    @patch.object(tools, "logger")
    @patch.object(tools, "add_openai_editor_tools")
    @patch.object(tools, "remove_anthropic_native_editor_tools")
    @patch.object(tools, "remove_text_file_neutral_tools")
    @patch.object(tools, "add_anthropic_native_editor_tools")
    @patch.object(tools, "remove_openai_editor_tools")
    @patch.object(tools, "add_text_file_neutral_tools")
    @patch.object(tools, "add_memory_tools")
    @patch.object(tools, "add_weather_tools")
    @patch.object(tools, "get_first_segment")
    @patch.object(tools, "GEMINI_TOOL_DESCRIPTIONS", new_callable=list)
    @patch.object(tools, "TOOL_DESCRIPTIONS", new_callable=list)
    @patch.object(tools, "TOOL_STATE", new_callable=dict)
    def test_configure_tools_anthropic_branch_without_matching_native(
        self,
        mock_state,
        mock_tool_desc,
        mock_gemini_desc,
        mock_get_first_segment,
        mock_add_weather,
        mock_add_memory,
        mock_add_text_neutral,
        mock_remove_openai_editors,
        mock_add_anthropic_native,
        mock_remove_text_neutral,
        mock_remove_anthropic_native,
        mock_add_openai_editors,
        mock_logger,
    ):
        """Anthropic model WITHOUT a matching native gate: fall back to surgical."""
        mock_tool_desc.extend(self.tool_desc)
        mock_gemini_desc.extend(self.gemini_desc)
        mock_get_first_segment.return_value = "anthropic"
        mock_add_anthropic_native.return_value = False  # no gate matched

        tools.configure_tools()

        mock_add_anthropic_native.assert_called_once()
        # No native → use surgical fallback.
        mock_add_text_neutral.assert_called_once()
        mock_remove_text_neutral.assert_not_called()
        mock_remove_openai_editors.assert_called_once()
        mock_add_openai_editors.assert_not_called()
        # Strip-then-add applies even when no native is added — keeps the
        # branch's behavior consistent and clears stale state from prior runs.
        mock_remove_anthropic_native.assert_called_once()


if __name__ == "__main__":
    unittest.main()
