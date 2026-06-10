import pytest
import unittest
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch, MagicMock
import io
import copy
import sys

import monitor.core.built_ins as built_ins
import monitor.lib.built_in_commands as bic

class TestConfigureBuiltIns(unittest.TestCase):
    @patch('monitor.lib.built_in_commands.print_colored_error')
    def test_compact_rejects_arguments(self, mock_error):
        built_ins.compact_command("unexpected")
        mock_error.assert_called_once_with(":compact does not accept arguments.")

    @patch('monitor.lib.built_in_commands.logger')
    @patch('monitor.lib.built_in_commands.print')
    @patch('monitor.lib.built_in_commands.config')
    def test_compact_runs_partial_preserve_flow(
        self,
        mock_config,
        mock_print,
        mock_logger,
    ):
        mock_config.CONVERSATION_HISTORY = [
            {"role": "user", "content": "older"},
            {"role": "assistant", "content": "older reply"},
            {"role": "user", "content": "recent"},
            {"role": "assistant", "content": "recent reply"},
        ]
        mock_config.RECENT_TURNS_PRESERVED_ON_COMPACT = 1
        mock_config.SUMMARIZATION_CONFIG = {"prompt": {"template": "x"}, "triggers": {}}
        mock_config.MODEL = "test-model"
        mock_config.SESSION_ID = "session-1"
        mock_config.SESSION_COMPACTION_COUNT = 0

        mock_split = MagicMock(return_value=2)
        mock_generate = MagicMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="summary text"))]
            )
        )
        mock_reset = MagicMock()
        fake_rate_limiter = SimpleNamespace(RATE_LIMITER=MagicMock())
        fake_litellm = SimpleNamespace(completion=MagicMock())

        with patch.dict(
            sys.modules,
            {
                "monitor.lib.history": SimpleNamespace(
                    _find_compaction_split_index=mock_split,
                    generate_conversation_summary=mock_generate,
                    reset_conversation_with_partial_summary=mock_reset,
                ),
                "monitor.lib.token_management": SimpleNamespace(count_message_tokens=MagicMock()),
                "monitor.lib.rate_limiter": fake_rate_limiter,
                "litellm": fake_litellm,
            },
        ), patch(
            "monitor.lib.built_in_commands.build_system_prompt",
            return_value="system prompt",
            create=True,
        ):
            built_ins.compact_command()

        mock_generate.assert_called_once()
        mock_reset.assert_called_once()
        reset_args = mock_reset.call_args.args
        self.assertEqual(reset_args[0], "summary text")
        self.assertEqual(
            reset_args[2],
            [
                {"role": "user", "content": "recent"},
                {"role": "assistant", "content": "recent reply"},
            ],
        )
        self.assertIs(reset_args[3], mock_config.CONVERSATION_HISTORY)
        self.assertIs(reset_args[4], mock_logger)
        self.assertIs(reset_args[5], mock_config)
        self.assertEqual(mock_config.SESSION_COMPACTION_COUNT, 1)
        mock_print.assert_called_with("Conversation compacted.")

    @patch('monitor.lib.built_in_commands.logger')
    @patch('monitor.lib.built_in_commands.print')
    @patch('monitor.lib.built_in_commands.config')
    @patch('monitor.lib.built_in_commands._find_compaction_split_index', create=True)
    def test_compact_noop_when_history_too_short(
        self,
        mock_split,
        mock_config,
        mock_print,
        mock_logger,
    ):
        mock_config.CONVERSATION_HISTORY = [{"role": "user", "content": "only"}]
        mock_config.RECENT_TURNS_PRESERVED_ON_COMPACT = 6
        mock_split.return_value = None

        built_ins.compact_command()

        mock_print.assert_called_with("Not enough history to compact yet.")
        mock_logger.info.assert_called_once()

    @patch('monitor.core.built_ins.append_function_to_built_ins')
    @patch('monitor.core.built_ins.edit_macros_command')
    def test_edit_macros_command_registration_and_invocation(self, mock_edit_macros_command, mock_append):
        """
        Test that :edit_macros is registered and that invoking it calls the correct function.
        """
        # Will store all registrations as dicts (as passed to append_function_to_built_ins)
        registrations = []
        def side_effect(reg_dict):
            registrations.append(reg_dict)
        mock_append.side_effect = side_effect

        # Run the registration
        built_ins.configure_built_ins()

        # Find the :edit_macros registration
        found = [d for d in registrations if d.get("command") == ":edit_macros"]
        self.assertEqual(len(found), 1, "Should register :edit_macros exactly once")
        macro_cmd = found[0]
        macro_func = macro_cmd["function"]

        # Call the registered function and confirm it calls edit_macros_command
        macro_func("test arg")
        mock_edit_macros_command.assert_called_once_with("test arg")

    @patch('monitor.core.built_ins.reload_macros_command')
    @patch('monitor.core.built_ins.append_function_to_built_ins')
    def test_reload_macros_command_registration_and_invocation(self, mock_append, mock_reload):
        """
        Test that :reload_macros is registered and invoking it calls core.built_ins.reload_macros_command.
        """
        registrations = []
        mock_append.side_effect = lambda reg: registrations.append(reg)

        # Run the registration
        built_ins.configure_built_ins()

        # Find the :reload_macros registration
        found = [r for r in registrations if r.get("command") == ":reload_macros"]
        self.assertEqual(len(found), 1, "Should register :reload_macros exactly once")
        reload_reg = found[0]
        reload_func = reload_reg["function"]

        # Call the registered function
        reload_func("test")
        mock_reload.assert_called_once_with("test")
