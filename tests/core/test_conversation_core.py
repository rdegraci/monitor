import unittest
from unittest.mock import patch, MagicMock, call
import monitor.core.conversation as conversation

class TestConversation(unittest.TestCase):
    @patch('monitor.core.conversation.prepare_query_context')
    @patch('monitor.core.conversation.get_llm_initial_completion')
    @patch('monitor.core.conversation.process_response_by_type')
    @patch('monitor.core.conversation.determine_response_type', return_value='direct')
    def test_query(self, mock_determine, mock_process, mock_llm_init, mock_prepare):
        # get_llm_initial_completion returns (response, error)
        fake_choices = [MagicMock(message='msg')]
        fake_response = MagicMock(choices=fake_choices)
        mock_llm_init.return_value = (fake_response, None)
        mock_process.return_value = 'FINAL RESULT'
        result = conversation.query('user input')
        mock_prepare.assert_called_once_with('user input')
        mock_llm_init.assert_called_once()
        mock_process.assert_called_once_with('direct', fake_response, 'msg')
        self.assertEqual(result, 'FINAL RESULT')

    @patch('monitor.core.conversation.config', new=MagicMock(MAX_TOKEN_COUNT=1048576))
    def test_handle_token_limit(self):
        self.assertEqual(conversation.handle_token_limit(42, 12), 1048576)

    @patch('monitor.core.conversation.prepend_memory_to_history')
    @patch('monitor.core.conversation.append_conversation_history')
    def test_prepare_query_context(self, mock_append, mock_prepend):
        # The function just calls the two helpers and passes params
        with patch('monitor.core.conversation.config', new=MagicMock()):
            with patch('monitor.core.conversation.SYSTEM_PROMPT', 'PROMPT'):
                conversation.prepare_query_context('foo')
                mock_prepend.assert_called_once()
                mock_append.assert_called_once()

    @patch('monitor.core.conversation.clear_screen')
    def test_conversation_history_command_empty(self, mock_clear):
        with patch('monitor.core.conversation.config', new=MagicMock(CONVERSATION_HISTORY=[])):
            with patch('builtins.print') as mock_print:
                conversation.conversation_history_command(None)
                mock_print.assert_any_call('No conversation history to display.')

    @patch('monitor.core.conversation.clear_screen')
    @patch('builtins.input', side_effect=['n', 'q'])
    def test_conversation_history_command_pagination(self, mock_input, mock_clear):
        fake_history = [{"role": "user", "content": f"Q{i}"} for i in range(15)]
        with patch('monitor.core.conversation.config', new=MagicMock(CONVERSATION_HISTORY=fake_history)):
            with patch('builtins.print') as mock_print:
                conversation.conversation_history_command(None, page_size=10)
                # Print is called with navigation prompt at least twice
                nav_prompt = "Press 'n' for next, 'p' for previous, 'q' to quit"
                nav_calls = [c for c in mock_print.call_args_list if nav_prompt in ''.join(map(str, c[0]))]
                self.assertGreaterEqual(len(nav_calls), 2)

if __name__ == "__main__":
    unittest.main()
