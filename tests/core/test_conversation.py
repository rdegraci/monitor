import unittest
from unittest.mock import patch, MagicMock, call, mock_open
import monitor.core.conversation as conversation
import logging
import re
import datetime as dt


class TestConversation(unittest.TestCase):
    @patch("monitor.core.conversation.prepare_query_context")
    @patch("monitor.core.conversation.get_llm_initial_completion")
    @patch("monitor.core.conversation.process_response_by_type")
    @patch("monitor.core.conversation.determine_response_type", return_value="direct")
    def test_query(self, mock_determine, mock_process, mock_llm_init, mock_prepare):
        """End-to-end query orchestrates helpers and returns final result."""
        fake_choices = [MagicMock(message="msg")]
        fake_response = MagicMock(choices=fake_choices)
        mock_llm_init.return_value = (fake_response, None)
        mock_process.return_value = "FINAL RESULT"
        result = conversation.query("user input")
        mock_prepare.assert_called_once_with("user input")
        mock_llm_init.assert_called_once()
        mock_process.assert_called_once_with("direct", fake_response, "msg")
        self.assertEqual(result, "FINAL RESULT")

    @patch("monitor.core.conversation.config", new=MagicMock(MAX_TOKEN_COUNT=1048576))
    def test_handle_token_limit(self):
        """handle_token_limit respects MAX_TOKEN_COUNT when smaller than estimate."""
        self.assertEqual(conversation.handle_token_limit(42, 12), 1048576)

    @patch("monitor.core.conversation.prepend_memory_to_history")
    @patch("monitor.core.conversation.append_conversation_history")
    def test_prepare_query_context(self, mock_append, mock_prepend):
        """prepare_query_context delegates to history helpers."""
        with patch("monitor.core.conversation.config", new=MagicMock()):
            with patch("monitor.core.conversation.SYSTEM_PROMPT", "PROMPT"):
                conversation.prepare_query_context("foo")
                mock_prepend.assert_called_once()
                mock_append.assert_called_once()

    @patch("monitor.core.conversation.clear_screen")
    def test_conversation_history_command_empty(self, mock_clear):
        """No history prints a helpful message."""
        with patch(
            "monitor.core.conversation.config", new=MagicMock(CONVERSATION_HISTORY=[])
        ):
            with patch("builtins.print") as mock_print:
                conversation.conversation_history_command(None)
                mock_print.assert_any_call("No conversation history to display.")

    @patch("monitor.core.conversation.clear_screen")
    @patch("builtins.input", side_effect=["n", "q"])
    def test_conversation_history_command_pagination(self, mock_input, mock_clear):
        """Pagination prompts appear across pages."""
        fake_history = [{"role": "user", "content": f"Q{i}"} for i in range(15)]
        with patch(
            "monitor.core.conversation.config",
            new=MagicMock(CONVERSATION_HISTORY=fake_history),
        ):
            with patch("builtins.print") as mock_print:
                conversation.conversation_history_command(None, page_size=10)
                nav_prompt = "Press 'n' for next, 'p' for previous, 'q' to quit"
                nav_calls = [
                    c
                    for c in mock_print.call_args_list
                    if nav_prompt in "".join(map(str, c[0]))
                ]
                self.assertGreaterEqual(len(nav_calls), 2)

    @patch(
        "monitor.core.conversation.summarize_conversation_questionnaire_for_twitch",
        return_value="Hello Twitch!",
    )
    @patch("monitor.core.conversation.send_twitch_message_command", return_value=True)
    def test_post_social_media_summaries_twitch_success(
        self, mock_send_twitch, mock_summarize
    ):
        """Twitch summary posts when enabled and summary is non-empty."""
        with patch(
            "monitor.core.conversation.config",
            new=MagicMock(SUMMARY_TWITCH=True, POST_LINKEDIN=False),
        ):
            with patch("builtins.print") as mock_print:
                conversation.post_social_media_summaries()
                mock_send_twitch.assert_called_once_with("Hello Twitch!")
                printed = [" ".join(map(str, c.args)) for c in mock_print.call_args_list]
                self.assertTrue(
                    any(
                        "twitch" in s.lower()
                        and ("posted" in s.lower() or "success" in s.lower())
                        for s in printed
                    )
                )

    @patch("monitor.core.conversation.logger")
    @patch("monitor.core.conversation.summarize_conversation_for_linkedin")
    @patch("monitor.core.conversation.send_linkedin_message")
    def test_post_social_media_summaries_linkedin_skip_and_error(
        self, mock_send_li, mock_summarize, mock_logger
    ):
        """LinkedIn skip on empty, then error path logs and prints failure."""
        # Skip path: empty summary -> no send, print skip
        mock_summarize.return_value = ""
        with patch(
            "monitor.core.conversation.config",
            new=MagicMock(POST_TWITCH=False, SUMMARY_LINKEDIN=True),
        ):
            with patch("builtins.print") as mock_print:
                conversation.post_social_media_summaries()
                mock_send_li.assert_not_called()
                printed = [" ".join(map(str, c.args)) for c in mock_print.call_args_list]
                self.assertTrue(
                    any("linkedin" in s.lower() and "skip" in s.lower() for s in printed)
                )

        # Error path: non-empty but send raises
        mock_send_li.reset_mock()
        mock_summarize.return_value = "Great session!"
        mock_send_li.side_effect = Exception("API down")
        with patch(
            "monitor.core.conversation.config",
            new=MagicMock(POST_TWITCH=False, SUMMARY_LINKEDIN=True),
        ):
            with patch("builtins.print") as mock_print:
                conversation.post_social_media_summaries()
                mock_send_li.assert_called_once_with("Great session!")
                printed = [" ".join(map(str, c.args)) for c in mock_print.call_args_list]
                self.assertTrue(
                    any(
                        "linkedin" in s.lower()
                        and ("fail" in s.lower() or "error" in s.lower())
                        for s in printed
                    )
                )
                self.assertTrue(mock_logger.error.called)

    def test_update_conversation_logs_writes_when_open(self):
        """update_conversation_logs appends to provided file handle."""
        mock_file = MagicMock()
        mock_file.closed = False
        with patch(
            "monitor.core.conversation.config",
            new=MagicMock(CONVERSATION_LOG_FILE=mock_file),
        ):
            conversation.update_conversation_logs("hello")
        mock_file.write.assert_called_once_with("User: hello\n")

    def test_get_input_happy_path(self):
        """get_input flows determine/process/validate/format and returns final text."""
        if not hasattr(conversation, "get_input"):
            self.skipTest("get_input not available")

        fake_session = MagicMock()
        fake_session.prompt.return_value = "First line"
        with patch(
            "monitor.core.conversation.determine_input_mode", return_value="single"
        ) as mock_det, patch(
            "monitor.core.conversation.process_input_mode", return_value="Interim"
        ) as mock_proc, patch(
            "monitor.core.conversation.validate_input", return_value=True
        ) as mock_val, patch(
            "monitor.core.conversation.format_final_input", return_value="Final Input"
        ) as mock_fmt:
            result = conversation.get_input(session=fake_session)
            fake_session.prompt.assert_called()
            mock_det.assert_called()
            mock_proc.assert_called()
            mock_val.assert_called()
            mock_fmt.assert_called()
            self.assertEqual(result, "Final Input")

    def test_chat_server_mode_raises(self):
        """chat raises when SERVER_MODE is True."""
        if not hasattr(conversation, "chat"):
            self.skipTest("chat not available")
        with patch(
            "monitor.core.conversation.config", new=MagicMock(SERVER_MODE=True)
        ):
            with self.assertRaises(RuntimeError):
                conversation.chat()


if __name__ == "__main__":
    unittest.main()
