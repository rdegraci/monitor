from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

import monitor.core.tooling as tooling
import inspect
from types import SimpleNamespace
import builtins
import contextlib
import monitor.core.conversation as conversation


class TestTooling(unittest.TestCase):
    def test_parse_function_args_dict(self):
        """parse_function_args should return dict unchanged when input is dict."""
        data = {"foo": 1}
        self.assertEqual(tooling.parse_function_args(data), data)

    def test_parse_function_args_json(self):
        """parse_function_args should parse JSON string to dict."""
        args_str = '{"foo": 42}'
        self.assertEqual(tooling.parse_function_args(args_str), {"foo": 42})

    def test_parse_function_args_invalid_json(self):
        """parse_function_args should raise on invalid JSON."""
        with self.assertRaises(Exception):
            tooling.parse_function_args("{bad")

    def test_create_tool_result_message(self):
        """create_tool_result_message should build a tool role message from result or error."""
        msg = tooling.create_tool_result_message("result", None, "id123")
        self.assertEqual(
            msg, {"role": "tool", "content": "result", "tool_call_id": "id123"}
        )

        error_msg = tooling.create_tool_result_message(None, "error!", "idX")
        self.assertEqual(
            error_msg, {"role": "tool", "content": "error!", "tool_call_id": "idX"}
        )

    @patch("monitor.core.tooling.AVAILABLE_TOOLS", new_callable=lambda: {"foo": lambda x: x + 1})
    @patch("monitor.core.tooling.count_message_tokens", return_value=1)
    @patch("monitor.lib.rate_limiter.RATE_LIMITER")
    def test_execute_tool_call_success(self, mock_limiter, mock_token_count, mock_available):
        """execute_tool_call should run a tool successfully."""
        tool_call = {"function": {"arguments": '{"x": 2}', "name": "foo"}}
        with patch.dict(tooling.AVAILABLE_TOOLS, {"foo": lambda x: x + 1}):
            result, err = tooling.execute_tool_call(tool_call)
            self.assertEqual(result, 3)
            self.assertIsNone(err)

    def test_execute_tool_call_emits_concise_tool_telemetry(self):
        """Tool telemetry should include path, output size, and truncation state."""
        tool_call = {
            "function": {
                "arguments": '{"path": "src/example.py"}',
                "name": "read_example",
            }
        }
        with (
            patch.dict(
                tooling.AVAILABLE_TOOLS,
                {"read_example": lambda path: "large output"},
                clear=True,
            ),
            patch.object(tooling, "count_message_tokens", return_value=20000),
            patch.multiple(
                tooling.config,
                CURRENT_TURN_TOOL_CALLS=[],
                RESPONSES_API=True,
                TOOL_OUTPUT_TOKEN_LIMIT=16384,
            ),
            patch.object(tooling.logger, "info") as mock_info,
        ):
            result, err = tooling.execute_tool_call(tool_call)
            recorded_tools = list(tooling.config.CURRENT_TURN_TOOL_CALLS)

        self.assertEqual(result, "large output")
        self.assertIsNone(err)
        self.assertEqual(recorded_tools, ["read_example"])
        mock_info.assert_called_once()
        fmt, *args = mock_info.call_args.args
        rendered = fmt % tuple(args)
        self.assertIn("[SPEND][TOOL]", rendered)
        self.assertIn("tool=read_example", rendered)
        self.assertIn("path='src/example.py'", rendered)
        self.assertIn("out_tokens=20000", rendered)
        self.assertIn("truncated=true", rendered)
        self.assertNotIn("large output", rendered)

    @patch("monitor.core.tooling.AVAILABLE_TOOLS", new_callable=dict)
    def test_execute_tool_call_missing(self, mock_available):
        """execute_tool_call should report error when tool is missing."""
        tool_call = {"function": {"arguments": "{}", "name": "notfound"}}
        result, err = tooling.execute_tool_call(tool_call)
        self.assertIsNone(result)
        self.assertIn("not found in available_functions", err)

    def test_create_function_result_message(self):
        """create_function_result_message should return (function_msg, result_msg)."""
        function_name = "echo"
        function_args = {"text": "hello"}
        result = "ok"
        func = getattr(tooling, "create_function_result_message")
        function_msg, result_msg = func(function_name, function_args, result)

        # Validate function message shape
        self.assertIsInstance(function_msg, dict)
        self.assertEqual(function_msg.get("role"), "assistant")
        self.assertEqual(function_msg.get("content"), "None")
        self.assertIn("function_call", function_msg)
        we = function_msg["function_call"]
        self.assertEqual(function_msg["function_call"]["name"], function_name)
        self.assertIn("arguments", function_msg["function_call"])

        # Validate result message
        self.assertIsInstance(result_msg, dict)
        self.assertEqual(result_msg.get("role"), "function")
        self.assertEqual(result_msg.get("name"), function_name)
        self.assertEqual(str(result_msg.get("content")), str(result))

    def test_process_function_result_with_print(self):
        """process_function_result should return a string and print output."""
        func = getattr(tooling, "process_function_result")
        with patch.object(builtins, "print") as mock_print:
            sig = inspect.signature(func)
            candidates = {
                "result": "done",
                "error": None,
                "name": "echo",
                "function_name": "echo",
                "tool_call_id": "tc1",
                "tool_call": {"id": "tc1", "function": {"name": "echo"}},
            }
            kwargs = {k: v for k, v in candidates.items() if k in sig.parameters}
            msg = func(**kwargs)
            self.assertIsInstance(msg, str)
            mock_print.assert_called()

    def test_parse_function_call_with_simple_namespace(self):
        """parse_function_call should return name and raw args string."""
        func = getattr(tooling, "parse_function_call")
        call_obj = SimpleNamespace(name="adder", arguments='{"x": 1, "y": 2}')

        # Try calling with positional; fall back to keyword names if needed.
        try:
            name, args = func(call_obj)
        except TypeError:
            tried = False
            name = args = None
            for key in ("function_call", "tool_call", "call", "obj", "message"):
                try:
                    name, args = func(**{key: call_obj})
                    tried = True
                    break
                except TypeError:
                    continue
            if not tried:
                # Last resort: use the first param name
                param_name = next(iter(inspect.signature(func).parameters))
                name, args = func(**{param_name: call_obj})

        self.assertEqual(name, "adder")
        self.assertIsInstance(args, str)
        self.assertEqual(args, '{"x": 1, "y": 2}')

    @patch("monitor.core.tooling.AVAILABLE_TOOLS", new_callable=dict)
    def test_execute_function_success(self, mock_available):
        """execute_function should run available function and return result."""
        with patch.dict(
            tooling.AVAILABLE_TOOLS, {"inc": lambda x: x + 1}, clear=True
        ):
            ctx = (
                patch.object(
                    tooling,
                    "configure_protocol_engine_message_history",
                    MagicMock(return_value=None),
                )
                if hasattr(tooling, "configure_protocol_engine_message_history")
                else contextlib.nullcontext()
            )
            with ctx:
                result, err = tooling.execute_function("inc", '{"x": 2}')
                self.assertEqual(result, 3)
                self.assertIsNone(err)

    @patch("monitor.core.tooling.AVAILABLE_TOOLS", new_callable=dict)
    def test_execute_function_missing(self, mock_available):
        """execute_function should return error when function not found."""
        ctx = (
            patch.object(
                tooling,
                "configure_protocol_engine_message_history",
                MagicMock(return_value=None),
            )
            if hasattr(tooling, "configure_protocol_engine_message_history")
            else contextlib.nullcontext()
        )
        with ctx:
            result, err = tooling.execute_function("not_here", "{}")
            self.assertIsNone(result)
            self.assertIn("not found in available_functions", err)

    @patch.object(tooling, "process_function_result")
    @patch.object(tooling, "create_function_result_message")
    @patch.object(tooling, "execute_function")
    @patch("monitor.core.tooling.update_conversation_history", create=True)
    @patch("monitor.core.tooling.process_response_by_finish_reason", create=True)
    @patch("monitor.core.tooling.get_llm_completion", create=True)
    @patch("monitor.core.tooling.append_to_history_with_count", create=True)
    def test_handle_end_to_end_with_patched_dependencies(
        self,
        mock_append,
        mock_get_completion,
        mock_process_finish,
        mock_update_history,
        mock_execute_function,
        mock_create_function_result_message,
        mock_process_function_result,
    ):
        """handle should orchestrate conversation and return final value with patched deps."""
        # Prepare mocks
        mock_append.return_value = None
        mock_get_completion.return_value = (
            SimpleNamespace(role="assistant", content="intermediate", tool_calls=None),
            None,
        )
        mock_process_finish.return_value = "assistant-final"
        mock_update_history.return_value = None
        mock_execute_function.return_value = ("res", None)
        mock_create_function_result_message.return_value = (
            {"role": "assistant", "content": "None", "function_call": {"name": "do", "arguments": "{}"}},
            {"role": "tool", "content": "res", "tool_call_id": "tc1"},
        )
        mock_process_function_result.return_value = "processed"

        handle = getattr(tooling, "handle")
        call_obj = SimpleNamespace(name="do", arguments="{}")
        result = handle(call_obj)

        self.assertEqual(result, "assistant-final")
        self.assertGreaterEqual(mock_get_completion.call_count, 1)
        mock_process_finish.assert_called()
        mock_append.assert_called()
        mock_update_history.assert_called()

    @patch.object(conversation, "extract_tool_calls")
    @patch.object(conversation, "append_to_history_with_count")
    @patch.object(conversation, "get_llm_completion")
    @patch.object(conversation, "process_response_by_finish_reason")
    @patch.object(conversation, "update_conversation_history")
    @patch.object(tooling, "execute_tool_call")
    @patch.object(tooling, "create_tool_result_message")
    def test_handle_tool_call_with_patched_conversation(
        self,
        mock_create_tool_result_message,
        mock_execute_tool_call,
        mock_update_conversation_history,
        mock_process_response_by_finish_reason,
        mock_get_llm_completion,
        mock_append_to_history_with_count,
        mock_extract_tool_calls,
    ):
        """handle_tool_call should execute tool and process follow-up with patched conversation."""
        mock_extract_tool_calls.return_value = [
            {"id": "tc1", "type": "function", "function": {"name": "ok", "arguments": "{}"}}
        ]
        mock_execute_tool_call.return_value = ("result", None)
        mock_create_tool_result_message.return_value = {
            "role": "tool",
            "content": "result",
            "tool_call_id": "tc1",
        }
        mock_get_llm_completion.return_value = (
            SimpleNamespace(role="assistant", content="final"),
            None,
        )
        mock_process_response_by_finish_reason.return_value = "final"
        mock_update_conversation_history.return_value = None

        handle_tool_call = getattr(tooling, "handle_tool_call")
        dummy_response = object()
        result = handle_tool_call(dummy_response)

        self.assertEqual(result, "final")
        mock_extract_tool_calls.assert_called()
        mock_execute_tool_call.assert_called_once()
        mock_create_tool_result_message.assert_called_once()
        mock_append_to_history_with_count.assert_called()
        mock_get_llm_completion.assert_called()
        mock_process_response_by_finish_reason.assert_called()
        mock_update_conversation_history.assert_called()

    @patch("monitor.core.tooling.create_tool_result_message")
    @patch("monitor.core.tooling.execute_tool_call")
    @patch("monitor.core.tooling.config")
    def test_handle_tool_call_preserves_partial_protocol_state_on_followup_error(
        self,
        mock_config,
        mock_execute_tool_call,
        mock_create_tool_result_message,
    ):
        """Once assistant/tool protocol state is committed, follow-up failure must not pop it."""
        history = [{"role": "user", "content": "question"}]
        mock_config.CONVERSATION_HISTORY = history
        mock_config.MAX_TOOL_CALL_DEPTH = 8
        mock_config.MAX_REPEATED_TOOL_CALLS = 3
        mock_config.SESSION_TOOL_CALL_COUNT = 0
        mock_config.SESSION_LOOP_DETECTOR_TRIPS = 0
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            {
                                "id": "tc1",
                                "type": "function",
                                "function": {"name": "ok", "arguments": "{}"},
                            }
                        ],
                    )
                )
            ]
        )
        mock_execute_tool_call.return_value = ("tool output", None)
        mock_create_tool_result_message.return_value = {
            "role": "tool",
            "content": "tool output",
            "tool_call_id": "tc1",
        }

        def append_side_effect(message, *_a, **_k):
            history.append(message)

        with patch("monitor.core.conversation.append_to_history_with_count") as mock_append, patch(
            "monitor.core.conversation.get_llm_completion", return_value=(None, "HTTP 500")
        ), patch("monitor.core.conversation.extract_tool_calls") as mock_extract:
            mock_append.side_effect = append_side_effect
            mock_extract.side_effect = lambda _response: append_side_effect(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "tc1",
                            "type": "function",
                            "function": {"name": "ok", "arguments": "{}"},
                        }
                    ],
                }
            ) or [
                {
                    "id": "tc1",
                    "type": "function",
                    "function": {"name": "ok", "arguments": "{}"},
                }
            ]
            result = tooling.handle_tool_call(response)

        self.assertEqual(result, "HTTP 500")
        self.assertEqual(history[0], {"role": "user", "content": "question"})
        self.assertEqual(history[1]["role"], "assistant")
        self.assertEqual(history[1]["tool_calls"][0]["id"], "tc1")
        self.assertEqual(history[2]["role"], "tool")
        self.assertEqual(history[2]["tool_call_id"], "tc1")


if __name__ == "__main__":
    unittest.main()
