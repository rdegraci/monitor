
import unittest
from unittest.mock import patch, MagicMock, call
from types import SimpleNamespace

import monitor.core.llm as llm

class TestLLM(unittest.TestCase):

    def test_determine_response_type(self):
        resp = SimpleNamespace()
        resp.tool_calls = [{"something": "here"}]
        resp.function_call = None
        self.assertEqual(llm.determine_response_type(resp), "tool_call")
        
        resp.tool_calls = []
        resp.function_call = {"x": 1}
        self.assertEqual(llm.determine_response_type(resp), "function_call")
        
        resp.tool_calls = None
        resp.function_call = None
        self.assertEqual(llm.determine_response_type(resp), "direct")

    def test_process_response_by_finish_reason_refusal(self):
        llm.config.CONVERSATION_HISTORY[:] = [
            {"role": "user", "content": "bad"},
            {"role": "assistant", "content": "..."},
        ]
        resp = SimpleNamespace(choices=[SimpleNamespace(finish_reason='refusal')])
        msg = llm.process_response_by_finish_reason(resp)
        self.assertIn("refused", msg)
        self.assertTrue(len(llm.config.CONVERSATION_HISTORY) < 2)

    def test_process_response_by_finish_reason_stop(self):
        llm.config.CONVERSATION_LOG_FILE = MagicMock()
        llm.config.CONVERSATION_LOG_FILE.closed = False
        message = SimpleNamespace(content="answer")
        choice = SimpleNamespace(finish_reason='stop', message=message)
        resp = SimpleNamespace(choices=[choice])
        msg = llm.process_response_by_finish_reason(resp)
        self.assertEqual(msg, "answer")

    def test_process_response_by_finish_reason_length(self):
        llm.config.CONVERSATION_LOG_FILE = MagicMock()
        llm.config.CONVERSATION_LOG_FILE.closed = False
        message = SimpleNamespace(content="partial", role="assistant")
        choice = SimpleNamespace(finish_reason='length', message=message)
        resp = SimpleNamespace(choices=[choice])
        ret = llm.process_response_by_finish_reason(resp)
        # Fix: assertion per instructions
        self.assertEqual(ret, "Length too long.")

    def test_process_response_by_finish_reason_content_filter(self):
        llm.config.CONVERSATION_LOG_FILE = MagicMock()
        llm.config.CONVERSATION_LOG_FILE.closed = False
        message = SimpleNamespace(content="sensitive")
        choice = SimpleNamespace(finish_reason='content_filter', message=message)
        resp = SimpleNamespace(choices=[choice])
        out = llm.process_response_by_finish_reason(resp)
        self.assertIn("filtered", out)

    def test_process_response_by_finish_reason_tool_calls(self):
        llm.config.CONVERSATION_LOG_FILE = MagicMock()
        llm.config.CONVERSATION_LOG_FILE.closed = False
        message = SimpleNamespace(content="tools", tool_calls=[1])
        choice = SimpleNamespace(finish_reason='tool_calls', message=message)
        resp = SimpleNamespace(choices=[choice])
        out = llm.process_response_by_finish_reason(resp)
        # Fix: assertIsNone per instructions
        self.assertIsNone(out)

    def test_process_response_by_finish_reason_unexpected(self):
        llm.config.CONVERSATION_LOG_FILE = MagicMock()
        llm.config.CONVERSATION_LOG_FILE.closed = False
        message = SimpleNamespace(content="fallback")
        choice = SimpleNamespace(finish_reason='unknown_branch', message=message)
        resp = SimpleNamespace(choices=[choice])
        out = llm.process_response_by_finish_reason(resp)
        # Fix: assertion should check for Unexpected finish reason string
        self.assertIn("Unexpected finish reason: unknown_branch", out)

    @patch("monitor.core.llm.handle_tool_call", return_value="tool_called")
    def test_process_response_by_type_tool_call(self, mock_handle_tool_call):
        # Fix: pass three arguments to process_response_by_type, including response_message
        resp = SimpleNamespace(tool_calls=[{"data": "foo"}], function_call=None, content=None)
        resp_msg = SimpleNamespace()  # minimal mock
        with patch("monitor.core.llm.append_to_history_with_count") as m:
            ret = llm.process_response_by_type("tool_call", resp, resp_msg)
        self.assertEqual(ret, "tool_called")
        mock_handle_tool_call.assert_called_once_with(resp)

    @patch("monitor.core.llm.handle", return_value="func_called")
    def test_process_response_by_type_function_call(self, mock_handle):
        # Fix: pass three arguments to process_response_by_type, including response_message
        resp = SimpleNamespace(tool_calls=[], function_call={"func": "data"}, content=None)
        resp_msg = SimpleNamespace(function_call={"func": "data"})
        with patch("monitor.core.llm.append_to_history_with_count") as m:
            ret = llm.process_response_by_type("function_call", resp, resp_msg)
        self.assertEqual(ret, "func_called")
        mock_handle.assert_called_once_with(resp_msg.function_call)

    @patch("monitor.core.llm.append_to_history_with_count")
    def test_extract_tool_calls(self, mock_append):
        # Fix: Pass mock with correct structure: response.choices[0].message.tool_calls
        # Setting nested message and tool_calls attribute
        message = SimpleNamespace(content="xyz", tool_calls=[{"a": 1}])
        choice = SimpleNamespace(message=message)
        sn = SimpleNamespace(choices=[choice])
        result = llm.extract_tool_calls(sn)
        self.assertEqual(result, [{"a": 1}])
        mock_append.assert_called_once()
        args, kwargs = mock_append.call_args
        self.assertEqual(args[0].content, "xyz")
        self.assertEqual(args[0].tool_calls, [{"a": 1}])

    @patch("monitor.core.llm.get_llm_completion", return_value=("delg_out", None))
    def test_get_llm_initial_completion_delegates(self, mock_get):
        out, err = llm.get_llm_initial_completion()
        self.assertEqual(out, "delg_out")
        self.assertIsNone(err)
        mock_get.assert_called_once()

    def test_attrdict_and_dict_to_attr(self):
        data = {"a": 1, "b": {"x": 99, "y": [{"z": 5}]}}
        ad = llm.dict_to_attr(data)
        self.assertEqual(ad.a, 1)
        self.assertEqual(ad.b.x, 99)
        self.assertEqual(ad.b.y[0].z, 5)
        self.assertEqual(ad["b"]["x"], 99)
        self.assertEqual(getattr(ad.b, "y")[0].z, 5)

    @patch("monitor.core.llm.litellm.completion", side_effect=Exception("fail"))
    @patch("monitor.core.llm.prepare_messages_with_cache_control", return_value=[{"role": "user", "content": "test2"}])
    @patch("monitor.core.llm.count_message_tokens", return_value=5)
    @patch("monitor.core.llm.load_user_preferences", return_value=None)
    @patch("monitor.core.llm.RATE_LIMITER")
    @patch("monitor.core.llm.function_descriptions", return_value=[])
    def test__get_llm_completion_error(self, mock_funcdesc, mock_limiter, mock_prefs, mock_token_count, mock_prep_msgs, mock_llm_completion):
        out, err = llm.get_llm_completion("log-test", "error-test")
        self.assertIsNone(out)
        self.assertIsNotNone(err)
        self.assertIn("fail", err)

    @patch("monitor.core.llm.litellm.completion")
    @patch("monitor.core.llm.prepare_messages_with_cache_control", return_value=[{"role": "user", "content": "test"}])
    @patch("monitor.core.llm.count_message_tokens", return_value=5)
    @patch("monitor.core.llm.load_user_preferences", return_value=None)
    @patch("monitor.core.llm.RATE_LIMITER")
    @patch("monitor.core.llm.function_descriptions", return_value=[])
    def test_get_llm_completion(self, mock_funcdesc, mock_limiter, mock_prefs, mock_token_count, mock_prep_msgs, mock_llm_completion):
        mock_llm_completion.return_value = MagicMock(usage=SimpleNamespace(total_tokens=7))
        response, err = llm.get_llm_completion()
        self.assertIsNone(err)
        mock_llm_completion.assert_called()
        mock_limiter.wait_if_needed.assert_called()

    @patch("monitor.core.llm.append_to_history_with_count")
    def test_process_direct_response(self, mock_append):
        llm.config.CONVERSATION_LOG_FILE = MagicMock()
        llm.config.CONVERSATION_LOG_FILE.closed = False
        llm.config.LAST_INPUT_WAS_VOICE = False
        respmsg = SimpleNamespace(content="some reply")
        out = llm.process_direct_response(respmsg)
        self.assertIn("some reply", out)
        mock_append.assert_called()

    @patch("monitor.core.llm.litellm.completion")
    @patch("monitor.core.llm.function_descriptions", return_value=[])
    def test_call_litellm_completion_injects_reasoning_params(self, mock_funcdesc, mock_llm_completion):
        llm.config.MAX_COMPLETION_TOKENS = 25000
        llm.config.REASONING_EFFORT = "medium"
        model_name = "openai/o3-test"
        messages = [{"role": "user", "content": "hello"}]
        mock_llm_completion.return_value = MagicMock()
        llm.call_litellm_completion(messages=messages, model=model_name)
        mock_llm_completion.assert_called_once()
        _, kwargs = mock_llm_completion.call_args
        self.assertIn("reasoning_effort", kwargs)
        self.assertEqual(kwargs.get("reasoning_effort"), llm.config.REASONING_EFFORT)
        self.assertIn("max_completion_tokens", kwargs)
        self.assertEqual(kwargs.get("max_completion_tokens"), llm.config.MAX_COMPLETION_TOKENS)

    @patch("monitor.core.llm.litellm.completion")
    @patch("monitor.core.llm.function_descriptions", return_value=[])
    def test_call_litellm_completion_no_reasoning_params_for_other_models(self, mock_funcdesc, mock_llm_completion):
        model_name = "openai/gpt-4o"
        messages = [{"role": "user", "content": "hi"}]
        mock_llm_completion.return_value = MagicMock()
        llm.call_litellm_completion(messages=messages, model=model_name)
        mock_llm_completion.assert_called_once()
        _, kwargs = mock_llm_completion.call_args
        self.assertNotIn("reasoning_effort", kwargs)
        self.assertNotIn("max_completion_tokens", kwargs)

if __name__ == "__main__":
    unittest.main()
