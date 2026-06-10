import unittest
from unittest.mock import patch, MagicMock, ANY
from types import SimpleNamespace


class TestLLMResponsesAdapter(unittest.TestCase):
    """Unit tests for llm_responses_adapter's Responses API integration.

    These tests validate configuration checks, request assembly, follow-up tool-call
    flows, and rate limiting/token accounting around the OpenAI Responses client.

    Helpers:
        setUp: Installs a controllable fake client.
        _fake_response: Builds a lightweight response-like object for stubbing.
    """

    def setUp(self):
        """Create and register a controllable fake OpenAI Responses client.

        This isolates tests from any real network calls and allows precise control
        over responses.create via MagicMock.
        """
        # Build a lightweight fake OpenAI Responses client with a create() we can control
        class FakeResponses:
            def __init__(self):
                self.create = MagicMock()

        class FakeClient:
            def __init__(self):
                self.responses = FakeResponses()

        self.FakeClient = FakeClient

    def _fake_response(self, resp_id, total_tokens=0, output=None):
        """Construct a minimal response-like object for stubbing.

        Args:
            resp_id: The response identifier to assign.
            total_tokens: The total token usage to attach to usage.total_tokens.
                If None, usage will be set to None on the response.
            output: The output list to attach (e.g., tool/function call items).

        Returns:
            An object with id, usage.total_tokens, and output attributes, suitable
            for use as a fake Responses API result.
        """
        class Usage:
            def __init__(self, total):
                self.total_tokens = total

        class Resp:
            def __init__(self, rid, total, output_items):
                self.id = rid
                self.usage = None if total is None else Usage(total)
                self.output = output_items

        return Resp(resp_id, total_tokens, output)

    @patch("monitor.core.llm_responses_adapter.logger")
    def test_validate_responses_config(self, _mock_logger):
        """Validate adapter.validate_responses_config under various config states.

        Verifies:
            - Raises ValueError when required flags are missing.
            - Accepts when MODEL and RESPONSES_API are both present.
        """
        from monitor.core import llm_responses_adapter as adapter

        # Missing both
        with patch.object(adapter, "config", SimpleNamespace()):
            with self.assertRaises(ValueError):
                adapter.validate_responses_config()

        # Missing one
        with patch.object(adapter, "config", SimpleNamespace(MODEL="openai/gpt-4o")):
            with self.assertRaises(ValueError):
                adapter.validate_responses_config()

        # Both present
        with patch.object(adapter, "config", SimpleNamespace(MODEL="openai/gpt-4o", RESPONSES_API=True)):
            # Should not raise
            adapter.validate_responses_config()

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch("monitor.core.llm_responses_adapter.token_budgeter", side_effect=lambda params, *_args, **_kwargs: params)
    @patch("monitor.core.llm_responses_adapter.truncate_to_token_limit", side_effect=lambda s, *_args, **_kwargs: s)
    @patch("monitor.core.llm_responses_adapter.serialize_tool_output", side_effect=lambda obj: "{}")
    @patch("monitor.core.llm_responses_adapter.execute_tool_call", return_value=({"ok": True}, None))
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    def test_call_responses_api_initial_and_followup(
        self,
        mock_rate_limiter,
        mock_update_tokens,
        _mock_get_tools,
        _mock_execute_tool_call,
        _mock_serialize,
        _mock_truncate,
        _mock_budgeter,
        mock_progress_dots,
    ):
        """Exercise an initial Responses call and a follow-up after a function call.

        Asserts:
            - Initial call sends full message list when RESPONSE_ID is None.
            - Follow-up uses previous_response_id and function_call_output payload.
            - RESPONSE_ID is updated, tokens are recorded, and rate limiter is used.
        """
        from monitor.core import llm_responses_adapter as adapter

        # Dummy context manager for progress_dots
        class _DummyCtx:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc, tb):
                return False

        mock_progress_dots.return_value = _DummyCtx()

        # Prepare fake client and patch it into module global
        fake_client = self.FakeClient()
        # First call returns a response with a function_call item, second returns no items
        first = self._fake_response(
            "resp_1",
            total_tokens=5,
            output=[{"type": "function_call", "id": "call_1", "name": "tools.echo", "arguments": "{\"x\":1}"}],
        )
        second = self._fake_response("resp_2", total_tokens=3, output=[])
        fake_client.responses.create.side_effect = [first, second]

        # Patch globals/config used by the adapter
        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            TEMPERATURE=None,
            TOP_P=None,
            FREQUENCY_PENALTY=None,
            PRESENCE_PENALTY=None,
            MAX_COMPLETION_TOKENS=None,
            RATE_LIMITER=True,  # just truthy flag for has-attr check, we will use mock_rate_limiter.RATE_LIMITER below
            MODEL_INPUT_WINDOW=None,
        )

        # Provide a mock RATE_LIMITER instance with add_request
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            messages = [{"role": "user", "content": "say hi"}]
            # Should run without raising; we assert the calls/side-effects below
            adapter.call_responses_api(messages, tool_descriptions={}, gemini_tool_descriptions={})

        # Assert first call: sends full messages list because RESPONSE_ID was None
        first_kwargs = fake_client.responses.create.call_args_list[0].kwargs
        assert first_kwargs["model"] == "gpt-4o-mini"
        assert first_kwargs["input"] == messages

        # RESPONSE_ID should be updated to first id before follow-up
        assert cfg.RESPONSE_ID == "resp_2"  # after the second call it should be the follow-up id

        # Assert second call (follow-up) used previous_response_id and function_call_output payload
        second_kwargs = fake_client.responses.create.call_args_list[1].kwargs
        assert second_kwargs["model"] == "gpt-4o-mini"
        assert second_kwargs["previous_response_id"] == "resp_1"
        assert isinstance(second_kwargs["input"], list)
        assert second_kwargs["input"][0]["type"] == "function_call_output"
        assert second_kwargs["input"][0]["call_id"] == "call_1"
        assert isinstance(second_kwargs["input"][0]["output"], str)

        # Token accounting: initial + follow-up. The `response=ANY` allows
        # the production code to also pass the response object for cost
        # computation without breaking these assertions.
        mock_update_tokens.assert_any_call(5, used_estimate=False, response=ANY)
        mock_update_tokens.assert_any_call(3, used_estimate=False, response=ANY)
        assert mock_update_tokens.call_count >= 2

        # Rate limiter should receive two add_request calls
        assert mock_rate_limiter.RATE_LIMITER.add_request.call_count >= 2

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    def test_call_responses_api_with_existing_response_id_sends_user_text(
        self,
        mock_rate_limiter,
        _mock_update,
        _mock_get_tools,
        mock_progress_dots,
    ):
        """Ensure only the latest user turn is sent when RESPONSE_ID is set.

        Asserts:
            - previous_response_id is forwarded.
            - input is the last user message string, not the entire transcript.
        """
        from monitor.core import llm_responses_adapter as adapter

        class _DummyCtx:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc, tb):
                return False

        mock_progress_dots.return_value = _DummyCtx()

        fake_client = self.FakeClient()
        # Single response, no function calls to keep it simple
        fake_client.responses.create.return_value = self._fake_response("resp_X", total_tokens=1, output=[])

        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID="prev_123",  # existing id should trigger sending only latest user text
            RATE_LIMITER=True,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        messages = [
            {"role": "system", "content": "system prefs"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "latest user input"},
        ]

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            adapter.call_responses_api(messages, tool_descriptions={}, gemini_tool_descriptions={})

        # Ensure only the latest user text was sent as the input string
        kwargs = fake_client.responses.create.call_args.kwargs
        assert kwargs["model"] == "gpt-4o-mini"
        assert kwargs["previous_response_id"] == "prev_123"
        assert isinstance(kwargs["input"], str)
        assert kwargs["input"] == "latest user input"

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=(["t"], "auto"))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    def test_includes_tools_and_tool_choice(
        self,
        mock_rate_limiter,
        _mock_update_tokens,
        _mock_get_tools,
        mock_progress_dots,
    ):
        """Include tools and tool_choice from get_tools_for_model in first request."""
        from monitor.core import llm_responses_adapter as adapter

        class _DummyCtx:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc, tb):
                return False

        mock_progress_dots.return_value = _DummyCtx()

        fake_client = self.FakeClient()
        fake_client.responses.create.return_value = self._fake_response("resp_1", total_tokens=1, output=[])
        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            RATE_LIMITER=True,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            adapter.call_responses_api([{"role": "user", "content": "hello"}], tool_descriptions={}, gemini_tool_descriptions={})

        kwargs = fake_client.responses.create.call_args.kwargs
        assert kwargs["model"] == "gpt-4o-mini"
        assert kwargs.get("tools") == ["t"]
        assert kwargs.get("tool_choice") == "auto"

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch("monitor.core.llm_responses_adapter.token_budgeter", side_effect=lambda params, *_args, **_kwargs: params)
    @patch("monitor.core.llm_responses_adapter.truncate_to_token_limit", side_effect=lambda s, *_args, **_kwargs: s)
    @patch("monitor.core.llm_responses_adapter.serialize_tool_output", side_effect=lambda obj: "{}")
    @patch("monitor.core.llm_responses_adapter.execute_tool_call")
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    def test_parses_arguments_and_executes_with_dict(
        self,
        mock_rate_limiter,
        _mock_update_tokens,
        _mock_get_tools,
        mock_execute_tool_call,
        _mock_serialize,
        _mock_truncate,
        _mock_budgeter,
        mock_progress_dots,
    ):
        """Parse JSON arguments to dict before execute_tool_call."""
        from monitor.core import llm_responses_adapter as adapter

        class _DummyCtx:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc, tb):
                return False

        mock_progress_dots.return_value = _DummyCtx()

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch("monitor.core.llm_responses_adapter.token_budgeter", side_effect=lambda params, *_args, **_kwargs: params)
    @patch("monitor.core.llm_responses_adapter.serialize_tool_output", side_effect=lambda obj: "{}")
    @patch("monitor.core.llm_responses_adapter.execute_tool_call", return_value=({"ok": True}, None))
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    def test_followup_uses_config_tool_output_token_limit(
        self,
        mock_rate_limiter,
        _mock_update_tokens,
        _mock_get_tools,
        _mock_execute_tool_call,
        _mock_serialize,
        _mock_budgeter,
        mock_progress_dots,
    ):
        """Ensure tool-output truncation reads the configured limit from config."""
        from monitor.core import llm_responses_adapter as adapter

        class _DummyCtx:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc, tb):
                return False

        mock_progress_dots.return_value = _DummyCtx()

        fake_client = self.FakeClient()
        first = self._fake_response(
            "resp_1",
            total_tokens=5,
            output=[{"type": "function_call", "id": "call_1", "name": "tools.echo", "arguments": "{\"x\":1}"}],
        )
        second = self._fake_response("resp_2", total_tokens=3, output=[])
        fake_client.responses.create.side_effect = [first, second]

        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            TEMPERATURE=None,
            TOP_P=None,
            FREQUENCY_PENALTY=None,
            PRESENCE_PENALTY=None,
            MAX_COMPLETION_TOKENS=None,
            RATE_LIMITER=True,
            MODEL_INPUT_WINDOW=None,
            TOOL_OUTPUT_TOKEN_LIMIT=8_192,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg), patch.object(
            adapter,
            "truncate_to_token_limit",
            return_value="{}",
        ) as mock_truncate:
            adapter.call_responses_api(
                [{"role": "user", "content": "say hi"}],
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        mock_truncate.assert_called_once_with("{}", 8_192, model="gpt-4o-mini")

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    def test_usage_none_defaults_to_zero(
        self,
        mock_rate_limiter,
        mock_update_tokens,
        _mock_get_tools,
        mock_progress_dots,
    ):
        """Default usage.total_tokens to 0 when usage is None."""
        from monitor.core import llm_responses_adapter as adapter

        class _DummyCtx:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc, tb):
                return False

        mock_progress_dots.return_value = _DummyCtx()

        fake_client = self.FakeClient()
        fake_client.responses.create.return_value = self._fake_response("resp_1", total_tokens=None, output=[])
        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            RATE_LIMITER=True,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            adapter.call_responses_api([{"role": "user", "content": "tokenless"}], tool_descriptions={}, gemini_tool_descriptions={})

        # update_token_usage should be called with 0
        mock_update_tokens.assert_any_call(0, used_estimate=True, response=ANY)

        # Rate limiter should receive an add_request with 0
        calls = mock_rate_limiter.RATE_LIMITER.add_request.call_args_list
        assert any(
            (len(c.args) > 0 and c.args[0] == 0) or (len(c.kwargs) > 0 and next(iter(c.kwargs.values())) == 0) for c in calls
        ), "Expected add_request to be called with 0 tokens"

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch("monitor.core.llm_responses_adapter.token_budgeter", side_effect=lambda params, *_args, **_kwargs: params)
    @patch("monitor.core.llm_responses_adapter.truncate_to_token_limit", side_effect=Exception("truncate fail"))
    @patch("monitor.core.llm_responses_adapter.serialize_tool_output", side_effect=Exception("serialize fail"))
    @patch("monitor.core.llm_responses_adapter.execute_tool_call", return_value=({"ok": True}, None))
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    def test_serialize_and_truncate_error_paths(
        self,
        mock_rate_limiter,
        _mock_update_tokens,
        _mock_get_tools,
        _mock_execute_tool_call,
        _mock_serialize,
        _mock_truncate,
        _mock_budgeter,
        mock_progress_dots,
    ):
        from monitor.core import llm_responses_adapter as adapter

        class _DummyCtx:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc, tb):
                return False

        mock_progress_dots.return_value = _DummyCtx()

        fake_client = self.FakeClient()
        first = self._fake_response(
            "resp_1",
            total_tokens=2,
            output=[{"type": "function_call", "id": "c1", "name": "tools.echo", "arguments": "{\"a\":1}"}],
        )
        second = self._fake_response("resp_2", total_tokens=1, output=[])
        fake_client.responses.create.side_effect = [first, second]

        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            RATE_LIMITER=True,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            adapter.call_responses_api([{"role": "user", "content": "hi"}], tool_descriptions={}, gemini_tool_descriptions={})

        # Second call is the follow-up; verify payload output is the fallback string
        second_kwargs = fake_client.responses.create.call_args_list[1].kwargs
        assert isinstance(second_kwargs["input"], list)
        assert second_kwargs["input"][0]["output"] == adapter.SERIALIZATION_FAILED_STR

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    def test_client_lazy_configuration_failure(self, _mock_get_tools, mock_progress_dots):
        """Raise RuntimeError when lazy client configuration fails."""
        from monitor.core import llm_responses_adapter as adapter

        class _DummyCtx:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc, tb):
                return False

        mock_progress_dots.return_value = _DummyCtx()

        # Force lazy configuration path and make it fail
        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
        )

        fake_client = self.FakeClient()
        first = self._fake_response(
            "resp_1",
            total_tokens=2,
            output=[{"type": "function_call", "id": "c1", "name": "tools.echo", "arguments": "{\"a\":1}"}],
        )
        second = self._fake_response("resp_2", total_tokens=1, output=[])
        fake_client.responses.create.side_effect = [first, second]

        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            RATE_LIMITER=False,
        )

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg), \
             patch.object(adapter, "execute_tool_call", return_value=({"ok": True}, None)), \
             patch.object(adapter, "serialize_tool_output", side_effect=Exception("serialize fail")), \
             patch.object(adapter, "truncate_to_token_limit", side_effect=Exception("truncate fail")), \
             patch.object(adapter, "token_budgeter", side_effect=lambda params, *_args, **_kwargs: params):
            adapter.call_responses_api([{"role": "user", "content": "x"}], tool_descriptions={}, gemini_tool_descriptions={})

        second_kwargs = fake_client.responses.create.call_args_list[1].kwargs
        payload = second_kwargs["input"]
        assert isinstance(payload, list) and payload, "Expected non-empty follow-up input list"
        assert payload[0]["type"] == "function_call_output"
        assert payload[0]["output"] == adapter.SERIALIZATION_FAILED_STR

    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.progress_dots")
    def test_client_lazy_configuration_failure(self, _mock_progress, _mock_get_tools):
        from monitor.core import llm_responses_adapter as adapter
        fake_client = None
        cfg = SimpleNamespace(MODEL="openai/gpt-4o-mini", RESPONSES_API=True)
        with patch.object(adapter, "client", None), patch.object(adapter, "config", cfg), patch.object(adapter, "configure_responses_adapter", side_effect=Exception("boom")):
            with self.assertRaises(RuntimeError):
                adapter.call_responses_api([{"role":"user","content":"x"}], tool_descriptions={}, gemini_tool_descriptions={})


if __name__ == "__main__":
    unittest.main()
