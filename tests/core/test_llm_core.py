import unittest
from unittest.mock import patch, MagicMock, mock_open
import types
import builtins
import monitor.core.llm as llm
from monitor.lib.built_in_commands import reasoning_command

class TestLLMCore(unittest.TestCase):
    def setUp(self):
        # Patch config values so we don't need real configs
        self.config_patcher = patch('monitor.lib.llm_utils.config', autospec=True)
        self.mock_config = self.config_patcher.start()
        self.addCleanup(self.config_patcher.stop)
        # Reasonable defaults
        self.mock_config.CONVERSATION_HISTORY = []
        self.mock_config.MODEL = 'openai/o3-test'
        self.mock_config.PREFERENCE_PROMPT = ''
        self.mock_config.REASONING_MAX_COMPLETION_TOKENS = 64
        self.mock_config.REASONING_MODEL_PREFIX = 'openai/o3'
        self.mock_config.MODEL_MAX_TPM = 4096
        self.mock_config.LAST_INPUT_WAS_VOICE = False
        self.mock_config.CONVERSATION_LOG_FILE = MagicMock(spec=['write', 'closed'])
        self.mock_config.CONVERSATION_LOG_FILE.closed = False
        self.mock_config.SUMMARIZATION_CONFIG = {}

    def test_attrdict_access_and_conversion(self):
        d = {'foo': {'bar': [1, {'baz': 5}]}}
        ad = llm.AttrDict(d)
        self.assertEqual(ad.foo.bar[1].baz, 5)
        # Test dict_to_attr recursively
        conv = llm.dict_to_attr({'a': {'b': [{'c': 9}]}})
        self.assertEqual(conv.a.b[0].c, 9)

    @patch('monitor.core.llm.prepare_messages_with_cache_control')
    @patch('monitor.core.llm.count_message_tokens', side_effect=lambda x: 1)
    @patch('monitor.core.llm.update_token_usage')
    @patch('monitor.core.llm.rate_limiter.RATE_LIMITER')
    @patch('monitor.core.llm.call_litellm_completion')
    def test_get_llm_completion_success(self, mock_call, mock_rl, mock_update_tokens, mock_count, mock_prepare):
        # Mocks
        mock_prepare.return_value = [{'role': 'user', 'content': 'test'}]
        mock_response = {'choices': [{}], 'usage': {'total_tokens': 5}}
        mock_call.return_value = mock_response
        # Should handle attributes too
        resp, err = llm.get_llm_completion()
        self.assertIsNone(err)
        self.assertTrue(hasattr(resp, 'choices'))
        mock_rl.wait_if_needed.assert_called()
        mock_update_tokens.assert_called()

    @patch('monitor.core.llm.prepare_messages_with_cache_control', side_effect=Exception("fail"))
    def test_get_llm_completion_exception(self, mock_prepare):
        resp, err = llm.get_llm_completion()
        self.assertIsNone(resp)
        self.assertIn('fail', err)

    def test_process_direct_response_and_voice(self):
        # Simulate TextToSpeech being used
        msg = MagicMock()
        msg.content = "Response"
        with patch('monitor.lib.llm_utils.config') as mock_llm_config, \
             patch('monitor.lib.llm_utils.TTS') as mock_tts, \
             patch('monitor.lib.llm_utils.append_to_history_with_count') as mock_hist, \
             patch('monitor.lib.token_management.count_message_tokens'), \
             patch('monitor.lib.token_management.update_token_usage'), \
             patch('monitor.lib.llm_utils.normalize_message') as mock_normalize:
            # Set up the config mock
            mock_llm_config.LAST_INPUT_WAS_VOICE = True
            # Mock normalize_message to return a dict
            mock_normalize.return_value = {'role': 'assistant', 'content': 'Response'}
            out = llm.process_direct_response(msg)
            mock_tts.speak.assert_called_with('Response')
            self.assertEqual(out, "Response")
            self.assertFalse(mock_llm_config.LAST_INPUT_WAS_VOICE)

    def test_determine_response_type(self):
        class Msg:
            tool_calls = [1]
            function_call = None
        self.assertEqual(llm.determine_response_type(Msg()), "tool_call")
        class Msg2:
            tool_calls = []
            function_call = True
        self.assertEqual(llm.determine_response_type(Msg2()), "function_call")
        class Msg3:
            tool_calls = []
            function_call = None
        self.assertEqual(llm.determine_response_type(Msg3()), "direct")

    @patch('monitor.core.llm.handle_tool_call', return_value='handled_tool')
    @patch('monitor.core.llm.handle', return_value='handled_function')
    @patch('monitor.core.llm.process_direct_response', return_value='handled_direct')
    def test_process_response_by_type(self, mock_direct, mock_handle, mock_tool):
        msg = MagicMock()
        msg.function_call = None
        msg.tool_calls = [1]
        out = llm.process_response_by_type('tool_call', 'resp', msg)
        self.assertEqual(out, 'handled_tool')
        out = llm.process_response_by_type('function_call', 'resp', msg)
        self.assertEqual(out, 'handled_function')
        out = llm.process_response_by_type('direct', 'resp', msg)
        self.assertEqual(out, 'handled_direct')

    def test_get_llm_initial_completion_delegation(self):
        with patch('monitor.core.llm.get_llm_completion', return_value=("ok", None)) as mock_get:
            result = llm.get_llm_initial_completion()
            self.assertEqual(result, ("ok", None))
            mock_get.assert_called()

    @patch('monitor.lib.llm_utils.append_to_history_with_count')
    def test_extract_tool_calls(self, mock_hist):
        resp = MagicMock()
        msg = MagicMock()
        msg.role = 'assistant'
        msg.tool_calls = [{'id': 'call_1', 'type': 'function', 'function': {'name': 'x', 'arguments': '{}'}}]
        resp.choices = [MagicMock(message=msg)]
        result = llm.extract_tool_calls(resp)
        self.assertEqual(result, [{'id': 'call_1', 'type': 'function', 'function': {'name': 'x', 'arguments': '{}'}}])
        mock_hist.assert_called()

    @patch('monitor.lib.llm_utils.append_to_history_with_count')
    def test_process_response_by_finish_reason(self, mock_hist):
        # refusal: pops user then assistant
        with patch('monitor.lib.llm_utils.config') as mock_llm_config:
            mock_llm_config.CONVERSATION_HISTORY = [
                {'role': 'user', 'content': 'hi'},
                {'role': 'assistant', 'content': 'AI'}
            ]
            mock_llm_config.MODEL = 'openai/o3-test'
            resp = MagicMock()
            resp.choices = [MagicMock(finish_reason="refusal")]
            with patch('monitor.lib.llm_utils.logger'):
                res = llm.process_response_by_finish_reason(resp)
            self.assertIn("Request was refused", res)
        # stop, content present
        with patch('monitor.lib.llm_utils.config') as mock_llm_config:
            mock_llm_config.CONVERSATION_LOG_FILE = MagicMock(spec=['write', 'closed'])
            mock_llm_config.CONVERSATION_LOG_FILE.closed = False
            mock_llm_config.MODEL = 'openai/o3-test'
            resp.choices = [MagicMock(finish_reason="stop", message=MagicMock(content="ok"))]
            with patch('monitor.lib.llm_utils.logger'):
                res = llm.process_response_by_finish_reason(resp)
            self.assertEqual(res, "ok")
        # stop, content None  
        with patch('monitor.lib.llm_utils.config') as mock_llm_config:
            mock_llm_config.CONVERSATION_LOG_FILE = MagicMock(spec=['write', 'closed'])
            mock_llm_config.CONVERSATION_LOG_FILE.closed = False
            mock_llm_config.MODEL = 'openai/o3-test'
            resp.choices = [MagicMock(finish_reason="stop", message=MagicMock(content=None))]
            with patch('monitor.lib.llm_utils.logger'):
                res = llm.process_response_by_finish_reason(resp)
            self.assertEqual(res, "Ok.")
        # length
        resp.choices = [MagicMock(finish_reason="length")]
        with patch('monitor.lib.llm_utils.logger'):
            res = llm.process_response_by_finish_reason(resp)
        self.assertIn("Length too long", res)
        # content_filter
        resp.choices = [MagicMock(finish_reason="content_filter")]
        with patch('monitor.lib.llm_utils.logger'):
            res = llm.process_response_by_finish_reason(resp)
        self.assertIn("Content filtered", res)
        # tool_calls
        resp.choices = [MagicMock(finish_reason="tool_calls")]
        with patch('monitor.lib.llm_utils.logger'):
            res = llm.process_response_by_finish_reason(resp)
        self.assertIsNone(res)
        # empty finish (xai/grok)
        with patch('monitor.lib.llm_utils.config') as mock_llm_config:
            mock_llm_config.MODEL = "xai/grok-v0"
            resp.choices = [MagicMock(finish_reason="")]
            with patch('monitor.lib.llm_utils.logger'):
                res = llm.process_response_by_finish_reason(resp)
            self.assertIsNone(res)
        # unexpected reason
        mock_choice = MagicMock()
        mock_choice.finish_reason = "unexpected"
        mock_choice.__str__ = lambda self: "mock_choice_obj"
        mock_choice.__repr__ = lambda self: "mock_choice_obj"
        resp.choices = [mock_choice]
        with patch('monitor.lib.llm_utils.logger') as mock_logger:
            res = llm.process_response_by_finish_reason(resp)
        self.assertIn("Unexpected finish reason", res)

    def test_call_litellm_completion_args(self):
        with patch('monitor.lib.llm_utils.config') as mock_llm_config, \
             patch('monitor.lib.llm_utils.litellm.completion') as mock_lite, \
             patch('monitor.lib.llm_utils.function_descriptions') as mock_funcdesc:
            
            # Set up proper mock returns
            mock_funcdesc.return_value = []
            mock_lite.return_value = {'ok': True}
            mock_llm_config.REASONING_MODEL_PREFIX = 'openai/o3'
            mock_llm_config.REASONING_EFFORT = 2
            mock_llm_config.REASONING_MAX_COMPLETION_TOKENS = 32
            
            result = llm.call_litellm_completion("openai/o3-test", [{'role': 'user', 'content': 'hi'}], tool_descriptions={}, gemini_tool_descriptions={})
            self.assertEqual(result, {'ok': True})
            
            # Check reasoning_effort+max_completion_tokens prepends
            mock_llm_config.REASONING_MODEL_PREFIX = 'openai/o3'
            mock_llm_config.REASONING_EFFORT = 4
            mock_llm_config.REASONING_MAX_COMPLETION_TOKENS = 33
            mock_funcdesc.return_value = []  # Reset mock for second call
            result = llm.call_litellm_completion("openai/o3-test", [{'role': 'user', 'content': 'hi'}], tool_descriptions={}, gemini_tool_descriptions={})
            self.assertEqual(mock_lite.call_args[1].get('reasoning_effort'), 4)
            self.assertEqual(mock_lite.call_args[1].get('max_completion_tokens'), 33)

    def test_auto_summarize_on_token_limit_retries_once(self):
        self.mock_config.MODEL = 'gpt-4o'
        self.mock_config.ENABLE_AUTO_SUMMARIZE_ON_LIMIT = True
        self.mock_config.MODEL_MAX_TPM = 5
        with patch('monitor.core.llm.prepare_messages_with_cache_control') as mock_prepare, \
             patch('monitor.core.llm.count_message_tokens') as mock_count, \
             patch('monitor.core.llm.call_litellm_completion') as mock_call, \
             patch('monitor.core.llm.generate_conversation_summary') as mock_gen, \
             patch('monitor.core.llm.reset_conversation_with_summary') as mock_reset, \
             patch('monitor.core.llm.rate_limiter.RATE_LIMITER') as mock_rl:
            mock_prepare.side_effect = [
                [{'role': 'user', 'content': f'm{i}'} for i in range(6)],
                [{'role': 'user', 'content': f'm{i}'} for i in range(2)]
            ]
            mock_count.side_effect = lambda msgs: len(msgs)
            mock_rl.wait_if_needed.return_value = True
            mock_call.return_value = {'choices': [{}], 'usage': {'total_tokens': 2}}
            mock_gen.return_value = "summary text"
            mock_reset.return_value = None
            resp, err = llm.get_llm_completion()
            self.assertIsNone(err)
            self.assertTrue(hasattr(resp, 'choices'))
            self.assertEqual(mock_gen.call_count, 1)
            self.assertEqual(mock_reset.call_count, 1)
            self.assertEqual(mock_call.call_count, 1)

    def test_auto_summarize_on_rate_limit_retries_once(self):
        self.mock_config.MODEL = 'gpt-4o'
        self.mock_config.ENABLE_AUTO_SUMMARIZE_ON_LIMIT = True
        self.mock_config.MODEL_MAX_TPM = 100
        with patch('monitor.core.llm.prepare_messages_with_cache_control') as mock_prepare, \
             patch('monitor.core.llm.count_message_tokens') as mock_count, \
             patch('monitor.core.llm.call_litellm_completion') as mock_call, \
             patch('monitor.core.llm.generate_conversation_summary') as mock_gen, \
             patch('monitor.core.llm.reset_conversation_with_summary') as mock_reset, \
             patch('monitor.core.llm.rate_limiter.RATE_LIMITER') as mock_rl:
            mock_prepare.return_value = [{'role': 'user', 'content': 'hi'} for _ in range(5)]
            mock_count.side_effect = lambda msgs: len(msgs)
            mock_rl.wait_if_needed.side_effect = [None, True]
            mock_call.return_value = {'choices': [{}], 'usage': {'total_tokens': 2}}
            mock_gen.return_value = "summary text"
            mock_reset.return_value = None
            resp, err = llm.get_llm_completion()
            self.assertIsNone(err)
            self.assertTrue(hasattr(resp, 'choices'))
            self.assertEqual(mock_gen.call_count, 1)
            self.assertEqual(mock_reset.call_count, 1)
            self.assertEqual(mock_call.call_count, 1)

    def test_auto_summarize_disabled_returns_error(self):
        self.mock_config.MODEL = 'gpt-4o'
        self.mock_config.ENABLE_AUTO_SUMMARIZE_ON_LIMIT = False
        self.mock_config.MODEL_MAX_TPM = 100
        with patch('monitor.core.llm.prepare_messages_with_cache_control') as mock_prepare, \
             patch('monitor.core.llm.count_message_tokens') as mock_count, \
             patch('monitor.core.llm.call_litellm_completion') as mock_call, \
             patch('monitor.core.llm.generate_conversation_summary') as mock_gen, \
             patch('monitor.core.llm.reset_conversation_with_summary') as mock_reset, \
             patch('monitor.core.llm.rate_limiter.RATE_LIMITER') as mock_rl:
            mock_prepare.return_value = [{'role': 'user', 'content': 'hi'} for _ in range(5)]
            mock_count.side_effect = lambda msgs: len(msgs)
            mock_rl.wait_if_needed.return_value = None
            resp, err = llm.get_llm_completion()
            self.assertIsNone(resp)
            self.assertIsNotNone(err)
            self.assertIn('Input too large', err)
            mock_gen.assert_not_called()
            mock_reset.assert_not_called()
            mock_call.assert_not_called()

    def test_auto_summarize_fallback_empty_summary(self):
        self.mock_config.MODEL = 'gpt-4o'
        self.mock_config.ENABLE_AUTO_SUMMARIZE_ON_LIMIT = True
        self.mock_config.MODEL_MAX_TPM = 100
        with patch('monitor.core.llm.prepare_messages_with_cache_control') as mock_prepare, \
             patch('monitor.core.llm.count_message_tokens') as mock_count, \
             patch('monitor.core.llm.call_litellm_completion') as mock_call, \
             patch('monitor.core.llm.generate_conversation_summary') as mock_gen, \
             patch('monitor.core.llm.reset_conversation_with_summary') as mock_reset, \
             patch('monitor.core.llm.rate_limiter.RATE_LIMITER') as mock_rl:
            mock_prepare.return_value = [{'role': 'user', 'content': 'hi'} for _ in range(5)]
            mock_count.side_effect = lambda msgs: len(msgs)
            mock_rl.wait_if_needed.side_effect = [None, True]
            mock_call.return_value = {'choices': [{}], 'usage': {'total_tokens': 3}}
            mock_gen.return_value = {}
            mock_reset.return_value = None
            resp, err = llm.get_llm_completion()
            self.assertIsNone(err)
            self.assertTrue(hasattr(resp, 'choices'))
            self.assertEqual(mock_gen.call_count, 1)
            self.assertEqual(mock_reset.call_count, 1)
            args, kwargs = mock_reset.call_args
            self.assertTrue(len(args) >= 1 and isinstance(args[0], str))

    def test_auto_summarize_only_once_then_error(self):
        self.mock_config.MODEL = 'gpt-4o'
        self.mock_config.ENABLE_AUTO_SUMMARIZE_ON_LIMIT = True
        self.mock_config.MODEL_MAX_TPM = 3
        with patch('monitor.core.llm.prepare_messages_with_cache_control') as mock_prepare, \
             patch('monitor.core.llm.count_message_tokens') as mock_count, \
             patch('monitor.core.llm.call_litellm_completion') as mock_call, \
             patch('monitor.core.llm.generate_conversation_summary') as mock_gen, \
             patch('monitor.core.llm.reset_conversation_with_summary') as mock_reset, \
             patch('monitor.core.llm.rate_limiter.RATE_LIMITER') as mock_rl:
            mock_prepare.side_effect = [
                [{'role': 'user', 'content': f'm{i}'} for i in range(4)],
                [{'role': 'user', 'content': f'm{i}'} for i in range(4)]
            ]
            mock_count.side_effect = lambda msgs: len(msgs)
            mock_rl.wait_if_needed.return_value = True
            mock_call.return_value = {'choices': [{}], 'usage': {'total_tokens': 3}}
            mock_gen.return_value = "summary text"
            mock_reset.return_value = None
            resp, err = llm.get_llm_completion()
            self.assertIsNone(resp)
            self.assertIsNotNone(err)
            self.assertIn('Input too large', err)
            self.assertEqual(mock_gen.call_count, 1)
            self.assertEqual(mock_reset.call_count, 1)
            mock_call.assert_not_called()

    def test_reasoning_command_sets_config(self):
        with patch('monitor.lib.built_in_commands.config') as mock_cfg:
            mock_cfg.REASONING_MODEL_PREFIX = 'openai/o3'
            mock_cfg.MODEL = 'openai/o3-test'
            reasoning_command(None)
            reasoning_command('help')
            reasoning_command('low')
            self.assertEqual(mock_cfg.REASONING_EFFORT, 'low')
            reasoning_command('minimal')
            self.assertEqual(mock_cfg.REASONING_EFFORT, 'minimal')
            reasoning_command('medium')
            self.assertEqual(mock_cfg.REASONING_EFFORT, 'medium')
            reasoning_command('high')
            self.assertEqual(mock_cfg.REASONING_EFFORT, 'high')
            reasoning_command('invalid')
            self.assertEqual(mock_cfg.REASONING_EFFORT, 'high')

if __name__ == "__main__":
    unittest.main()
