import unittest
from unittest.mock import patch, MagicMock, ANY
from types import SimpleNamespace
import json


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
        with patch.object(
            adapter,
            "config",
            SimpleNamespace(MODEL="openai/gpt-4o", RESPONSES_API=True),
        ):
            # Should not raise
            adapter.validate_responses_config()

    @patch("monitor.core.llm_responses_adapter.OpenAI")
    def test_configure_responses_adapter_uses_ollama_base_url(self, mock_openai):
        """Verify Ollama steady models configure the Responses client base URL."""
        from monitor.core import llm_responses_adapter as adapter

        cfg = SimpleNamespace(
            MODEL="ollama/llama3.1",
            OLLAMA_BASE_URL="http://127.0.0.1:11434",
            OPENAI_API_KEY=None,
        )

        with patch.object(adapter, "config", cfg):
            adapter.configure_responses_adapter()

        mock_openai.assert_called_once_with(base_url="http://127.0.0.1:11434")

    def test_build_prompt_cache_key_uses_session_model_and_shape(self):
        """Prompt cache keys should be stable across same-session request shapes."""
        from monitor.core import llm_responses_adapter as adapter

        cfg = SimpleNamespace(SESSION_ID="session-123")

        with patch.object(adapter, "config", cfg):
            assert adapter._build_prompt_cache_key("gpt-5.4", "turn") == (
                "m:r:v1:s:sion-123:m:gpt-5.4:q:turn"
            )


    def test_build_prompt_cache_key_truncates_tokens_within_length_limit(self):
        """Prompt cache keys should keep readable truncated tokens within the length limit."""
        from monitor.core import llm_responses_adapter as adapter

        cfg = SimpleNamespace(SESSION_ID="session-identifier-that-is-far-longer-than-expected")
        request_model = "openai/very-long-model-name-that-keeps-going-past-normal"
        request_shape = "tool-followup-shape-that-is-long"

        with patch.object(adapter, "config", cfg):
            cache_key = adapter._build_prompt_cache_key(request_model, request_shape)

        assert cache_key == "m:r:v1:s:expected:m:very-long-model-:q:tool-followu"
        assert len(cache_key) <= 64
    def test_calculate_followup_payload_budget_tool_result_request(self):
        """The pure reserve calculator should derive a payload budget from the
        usable window and named reserve buckets."""
        from monitor.core import llm_responses_adapter as adapter

        budget = adapter.calculate_followup_payload_budget(
            request_class=adapter.FOLLOWUP_REQUEST_CLASS_TOOL,

            input_window=10_000,
            base_safety_ratio=0.85,
            hidden_chain_reserve_by_class={
                adapter.FOLLOWUP_REQUEST_CLASS_TOOL: 4000,
            },
            hidden_chain_reserve_per_depth=1000,
            hidden_chain_reserve_cap_ratio=0.5,
            top_level_reserve_tokens=256,
            iteration=2,
            tool_schema_reserve_tokens=100,
            structured_payload_reserve_tokens=200,
        )

        assert budget["request_class"] == adapter.FOLLOWUP_REQUEST_CLASS_TOOL
        assert budget["usable_window"] == 8500
        assert budget["hidden_chain_reserve"] == 6000
        assert budget["tool_schema_reserve"] == 100
        assert budget["structured_payload_reserve"] == 200
        assert budget["top_level_reserve"] == 256
        assert budget["payload_budget"] == 1944
        assert budget["decision"] == adapter.FOLLOWUP_BUDGET_DECISION_SEND

    def test_calculate_followup_payload_budget_unknown_without_window(self):
        from monitor.core import llm_responses_adapter as adapter

        budget = adapter.calculate_followup_payload_budget(
            request_class=adapter.FOLLOWUP_REQUEST_CLASS_TOOL,
            input_window=None,
            base_safety_ratio=0.85,
            hidden_chain_reserve_by_class={},
            hidden_chain_reserve_per_depth=1000,
            hidden_chain_reserve_cap_ratio=0.5,
            top_level_reserve_tokens=256,
        )

        assert budget["payload_budget"] is None
        assert budget["decision"] == adapter.FOLLOWUP_BUDGET_DECISION_UNKNOWN

    def test_measure_followup_request_reserves_counts_structure(self):
        from monitor.core import llm_responses_adapter as adapter

        params = {
            "model": "gpt-4o-mini",
            "previous_response_id": "resp_1",
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": '{"ok": true, "value": 1}',
                }
            ],
            "tools": [{"type": "function", "function": {"name": "echo"}}],
            "tool_choice": "auto",
        }

        reserves = adapter.measure_followup_request_reserves(
            params,
            model_name="gpt-4o-mini",
        )

        assert reserves["tool_schema_reserve_tokens"] > 0
        assert reserves["structured_payload_reserve_tokens"] > 0


    def test_budget_followup_request_marks_chained_user_followup_unknown(self):
        from monitor.core import llm_responses_adapter as adapter

        params = {
            "model": "gpt-4o-mini",
            "previous_response_id": "resp_prev",
            "input": "latest user question",
        }

        with patch.object(adapter, "config", SimpleNamespace(TURN_ROUND_TRIPS=[])):
            _params_copy, budget = adapter.budget_followup_request(
                params,
                iteration=0,
                input_window=10_000,
            )

        assert budget["request_class"] == adapter.FOLLOWUP_REQUEST_CLASS_CHAINED
        assert budget["decision"] == adapter.FOLLOWUP_BUDGET_DECISION_UNKNOWN
        assert budget["payload_budget"] is None

    def test_budget_followup_request_keeps_tool_followup_send_decision(self):
        from monitor.core import llm_responses_adapter as adapter

        params = {
            "model": "gpt-4o-mini",
            "previous_response_id": "resp_prev",
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": "{}",
                }
            ],
        }

        with patch.object(adapter, "config", SimpleNamespace(TURN_ROUND_TRIPS=[])):
            _params_copy, budget = adapter.budget_followup_request(
                params,
                iteration=0,
                input_window=10_000,
            )

        assert budget["request_class"] == adapter.FOLLOWUP_REQUEST_CLASS_TOOL
        assert budget["decision"] == adapter.FOLLOWUP_BUDGET_DECISION_SEND
        assert isinstance(budget["payload_budget"], int)
    def test_compute_followup_hidden_chain_reserve_ramps_for_chained_followups(self):
        from monitor.core import llm_responses_adapter as adapter

        cfg = SimpleNamespace(
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS={
                "fresh_request": 0,
                "chained_user_followup": 2000,
                "tool_result_followup": 4000,
                "summarization_followup": 2000,
            },
            FOLLOWUP_DYNAMIC_CHAINED_RESERVE=True,
            FOLLOWUP_CHAINED_RESERVE_MIN_RT=20,
            FOLLOWUP_CHAINED_RESERVE_MAX_RT=45,
            FOLLOWUP_CHAINED_RESERVE_MAX_TOKENS=8000,
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH=1000,
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO=0.5,
            FOLLOWUP_BASE_SAFETY_RATIO=0.85,
            MODEL_INPUT_WINDOW=10_000,
            MODEL_CONTEXT_WINDOW=None,
        )

        with patch.object(adapter, "config", cfg):
            assert (
                adapter.compute_followup_hidden_chain_reserve(
                    adapter.FOLLOWUP_REQUEST_CLASS_CHAINED,
                    iteration=0,
                    input_window=10_000,
                )
                == 2000
            )
            assert (
                adapter.compute_followup_hidden_chain_reserve(
                    adapter.FOLLOWUP_REQUEST_CLASS_CHAINED,
                    iteration=20,
                    input_window=10_000,
                )
                == 2000
            )
            assert (
                adapter.compute_followup_hidden_chain_reserve(
                    adapter.FOLLOWUP_REQUEST_CLASS_CHAINED,
                    iteration=45,
                    input_window=10_000,
                )
                == 8000
            )
            assert (
                adapter.compute_followup_hidden_chain_reserve(
                    adapter.FOLLOWUP_REQUEST_CLASS_CHAINED,
                    iteration=30,
                    input_window=10_000,
                )
                == 4400
            )

    def test_infer_followup_iteration_uses_turn_round_trips_for_chained_requests(self):
        from monitor.core import llm_responses_adapter as adapter

        cfg = SimpleNamespace(TURN_ROUND_TRIPS=[3, 30])
        params = {
            adapter.REQUEST_PARAM_MODEL: "gpt-4o-mini",
            adapter.REQUEST_PREV_RESPONSE_ID: "resp_chain",
            adapter.REQUEST_PARAM_INPUT: "latest user turn",
        }

        with patch.object(adapter, "config", cfg):
            assert adapter.infer_followup_iteration(params, default_iteration=0) == 30

    def test_infer_followup_iteration_keeps_tool_followup_iteration(self):
        from monitor.core import llm_responses_adapter as adapter

        cfg = SimpleNamespace(TURN_ROUND_TRIPS=[45])
        params = {
            adapter.REQUEST_PARAM_MODEL: "gpt-4o-mini",
            adapter.REQUEST_PREV_RESPONSE_ID: "resp_chain",
            adapter.REQUEST_PARAM_INPUT: [
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": "{}",
                }
            ],
        }

        with patch.object(adapter, "config", cfg):
            assert adapter.infer_followup_iteration(params, default_iteration=2) == 2

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch(
        "monitor.core.llm_responses_adapter.token_budgeter",
        side_effect=lambda params, *_args, **_kwargs: params,
    )
    @patch(
        "monitor.core.llm_responses_adapter.truncate_to_token_limit",
        side_effect=lambda s, *_args, **_kwargs: s,
    )
    @patch(
        "monitor.core.llm_responses_adapter.serialize_tool_output",
        side_effect=lambda obj: "{}",
    )
    @patch(
        "monitor.core.llm_responses_adapter.execute_tool_call",
        return_value=({"ok": True}, None),
    )
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
            output=[
                {
                    "type": "function_call",
                    "id": "call_1",
                    "name": "tools.echo",
                    "arguments": '{"x":1}',
                }
            ],
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
            MODEL_INPUT_WINDOW=128_000,
            TOOL_OUTPUT_TOKEN_LIMIT=1_024,
        )

        # Provide a mock RATE_LIMITER instance with add_request
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            messages = [{"role": "user", "content": "say hi"}]
            # Should run without raising; we assert the calls/side-effects below
            adapter.call_responses_api(
                messages,
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        # Assert first call: sends full messages list because RESPONSE_ID was None
        first_kwargs = fake_client.responses.create.call_args_list[0].kwargs
        assert first_kwargs["model"] == "gpt-4o-mini"
        assert first_kwargs["input"] == messages

        assert first_kwargs["prompt_cache_retention"] == "24h"
        assert first_kwargs["prompt_cache_key"] == "m:r:v1:s:default:m:gpt-4o-mini:q:turn"

        # RESPONSE_ID should be updated to first id before follow-up
        assert cfg.RESPONSE_ID == "resp_2"  # after the second call it should be the follow-up id

        # Assert second call (follow-up) used previous_response_id and function_call_output payload
        second_kwargs = fake_client.responses.create.call_args_list[1].kwargs
        assert second_kwargs["model"] == "gpt-4o-mini"
        assert second_kwargs["prompt_cache_key"] == (
            "m:r:v1:s:default:m:gpt-4o-mini:q:tool-followu"
        )
        assert second_kwargs["prompt_cache_retention"] == "24h"
        assert second_kwargs["previous_response_id"] == "resp_1"
        assert isinstance(second_kwargs["input"], list)
        assert second_kwargs["input"][0]["type"] == "function_call_output"
        assert second_kwargs["input"][0]["call_id"] == "call_1"
        assert isinstance(second_kwargs["input"][0]["output"], str)

        # Token accounting: initial + follow-up. The `response=ANY` allows
        # the production code to also pass the response object for cost
        # computation without breaking these assertions.
        mock_update_tokens.assert_any_call(
            5,
            used_estimate=False,
            response=ANY,
            model="openai/gpt-4o-mini",
        )
        mock_update_tokens.assert_any_call(
            3,
            used_estimate=False,
            response=ANY,
            model="openai/gpt-4o-mini",
        )
        assert mock_update_tokens.call_count >= 2

        # Rate limiter should receive two add_request calls
        assert mock_rate_limiter.RATE_LIMITER.add_request.call_count >= 2

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    def test_call_responses_api_uses_adv_reasoning_model_for_turn_override(
        self,
        mock_rate_limiter,
        mock_update_tokens,
        _mock_get_tools,
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
        fake_client.responses.create.return_value = self._fake_response(
            "resp_adv",
            total_tokens=1,
            output=[],
        )

        cfg = SimpleNamespace(
            MODEL="openai/gpt-5.4-mini",
            ADV_REASONING_MODEL="openai/gpt-5.4",
            REASONING_MODEL_PREFIX="openai/gpt-5",
            CURRENT_TURN_REASONING_OVERRIDE="high",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            RATE_LIMITER=True,
            TEMPERATURE=None,
            TOP_P=None,
            FREQUENCY_PENALTY=None,
            PRESENCE_PENALTY=None,
            MAX_COMPLETION_TOKENS=4_000,
            REASONING_MAX_COMPLETION_TOKENS=25_000,
            ADV_REASONING_MODEL_OUTPUT_WINDOW=10_000,
            CURRENT_TURN_IS_COLLATION=False,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            adapter.call_responses_api(
                [{"role": "user", "content": "reason harder"}],
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        kwargs = fake_client.responses.create.call_args.kwargs
        assert kwargs["model"] == "gpt-5.4"
        assert kwargs["max_output_tokens"] == 10_000
        mock_update_tokens.assert_any_call(
            1,
            used_estimate=False,
            response=ANY,
            model="openai/gpt-5.4",
        )

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch(
        "monitor.core.llm_responses_adapter.token_budgeter",
        side_effect=lambda params, *_args, **_kwargs: params,
    )
    @patch(
        "monitor.core.llm_responses_adapter.truncate_to_token_limit",
        side_effect=lambda s, *_args, **_kwargs: s,
    )
    @patch(
        "monitor.core.llm_responses_adapter.serialize_tool_output",
        side_effect=lambda obj: "{}",
    )
    @patch(
        "monitor.core.llm_responses_adapter.execute_tool_call",
        return_value=(None, "Traceback (most recent call last): boom"),
    )
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    def test_call_responses_api_tool_failure_escalates_followup_to_adv_model(
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
            total_tokens=5,
            output=[
                {
                    "type": "function_call",
                    "id": "call_1",
                    "name": "tools.echo",
                    "arguments": '{"x":1}',
                }
            ],
        )
        second = self._fake_response("resp_2", total_tokens=3, output=[])
        fake_client.responses.create.side_effect = [first, second]

        cfg = SimpleNamespace(
            MODEL="openai/gpt-5.4-mini",
            ADV_REASONING_MODEL="openai/gpt-5.4",
            REASONING_MODEL_PREFIX="openai/gpt-5",
            CURRENT_TURN_REASONING_OVERRIDE=None,
            CURRENT_TURN_IS_COLLATION=False,
            ESCALATE_REASONING_ON_TOOL_FAILURE=True,
            REASONING_EFFORT="low",
            REASONING_BUMP_EFFORT="high",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            TEMPERATURE=None,
            TOP_P=None,
            FREQUENCY_PENALTY=None,
            PRESENCE_PENALTY=None,
            MAX_COMPLETION_TOKENS=4_000,
            REASONING_MAX_COMPLETION_TOKENS=25_000,
            ADV_REASONING_MODEL_OUTPUT_WINDOW=10_000,
            RATE_LIMITER=True,
            MODEL_INPUT_WINDOW=None,
            TOOL_OUTPUT_TOKEN_LIMIT=8_192,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            adapter.call_responses_api(
                [{"role": "user", "content": "try the tool"}],
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        first_kwargs = fake_client.responses.create.call_args_list[0].kwargs
        second_kwargs = fake_client.responses.create.call_args_list[1].kwargs
        assert first_kwargs["model"] == "gpt-5.4-mini"
        assert second_kwargs["model"] == "gpt-5.4"
        assert second_kwargs["max_output_tokens"] == 2_048
        assert cfg.CURRENT_TURN_REASONING_OVERRIDE == "high"

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch(
        "monitor.core.llm_responses_adapter.truncate_to_token_limit",
        side_effect=lambda s, *_args, **_kwargs: s,
    )
    @patch(
        "monitor.core.llm_responses_adapter.serialize_tool_output",
        side_effect=lambda obj: "{}",
    )
    @patch(
        "monitor.core.llm_responses_adapter.execute_tool_call",
        return_value=({"ok": True}, None),
    )
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    def test_followup_budgeter_uses_reserve_aware_payload_budget(
        self,
        mock_rate_limiter,
        _mock_update_tokens,
        _mock_get_tools,
        _mock_execute_tool_call,
        _mock_serialize,
        _mock_truncate,
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
            total_tokens=5,
            output=[
                {
                    "type": "function_call",
                    "id": "call_1",
                    "name": "tools.echo",
                    "arguments": '{"x":1}',
                }
            ],
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
            MODEL_INPUT_WINDOW=10_000,
            MODEL_CONTEXT_WINDOW=None,
            FOLLOWUP_BASE_SAFETY_RATIO=0.85,
            FOLLOWUP_TOPLEVEL_RESERVE_TOKENS=256,
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS={
                "fresh_request": 0,
                "chained_user_followup": 2000,
                "tool_result_followup": 4000,
                "summarization_followup": 2000,
            },
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH=1000,
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO=0.5,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        def fake_count_message_tokens(obj):
            if isinstance(obj, list):
                outputs = [item.get("output") for item in obj if isinstance(item, dict)]
                if any(output == "trimmed" for output in outputs):
                    return 1000
                return 4000
            return 10

        def fake_token_budgeter(params, input_window=100000, model_name=None):
            assert input_window == 1911
            trimmed = {
                **params,
                "input": [
                    {
                        **params["input"][0],
                        "output": "trimmed",
                    }
                ],
            }
            return trimmed

        with (
            patch.object(adapter, "client", fake_client),
            patch.object(adapter, "config", cfg),
            patch.object(
                adapter,
                "count_message_tokens",
                side_effect=fake_count_message_tokens,
            ),
            patch.object(
                adapter,
                "measure_followup_request_reserves",
                return_value={
                    "tool_schema_reserve_tokens": 111,
                    "structured_payload_reserve_tokens": 222,
                },
            ),
            patch.object(
                adapter,
                "token_budgeter",
                side_effect=fake_token_budgeter,
            ) as mock_budgeter,
        ):
            adapter.call_responses_api(
                [{"role": "user", "content": "say hi"}],
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        assert mock_budgeter.call_count == 1
        second_kwargs = fake_client.responses.create.call_args_list[1].kwargs
        assert second_kwargs["previous_response_id"] == "resp_1"
        assert second_kwargs["input"][0]["output"] == "trimmed"

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch(
        "monitor.core.llm_responses_adapter.truncate_to_token_limit",
        side_effect=lambda s, *_args, **_kwargs: s,
    )
    @patch(
        "monitor.core.llm_responses_adapter.serialize_tool_output",
        side_effect=lambda obj: "{}",
    )
    @patch(
        "monitor.core.llm_responses_adapter.execute_tool_call",
        return_value=({"ok": True}, None),
    )
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    def test_followup_budget_fallback_routes_to_summarization_followup(
        self,
        mock_rate_limiter,
        _mock_update_tokens,
        _mock_get_tools,
        _mock_execute_tool_call,
        _mock_serialize,
        _mock_truncate,
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
            total_tokens=5,
            output=[
                {
                    "type": "function_call",
                    "id": "call_1",
                    "name": "tools.echo",
                    "arguments": '{"x":1}',
                }
            ],
        )
        summary = self._fake_response("resp_summary", total_tokens=2, output=[])
        fake_client.responses.create.side_effect = [first, summary]

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
            MODEL_INPUT_WINDOW=10_000,
            MODEL_CONTEXT_WINDOW=None,
            TOOL_OUTPUT_TOKEN_LIMIT=8_192,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        fallback_budget = {
            "request_class": adapter.FOLLOWUP_REQUEST_CLASS_TOOL,
            "model_input_window": 10_000,
            "usable_window": 8_500,
            "hidden_chain_reserve": 6_000,
            "tool_schema_reserve": 0,
            "structured_payload_reserve": 0,
            "top_level_reserve": 256,
            "payload_budget": -1,
            "decision": adapter.FOLLOWUP_BUDGET_DECISION_FALLBACK,
        }

        with (
            patch.object(adapter, "client", fake_client),
            patch.object(adapter, "config", cfg),
            patch.object(
                adapter,
                "budget_followup_request",
                return_value=(
                    {
                        "model": "gpt-4o-mini",
                        "previous_response_id": "resp_1",
                        "input": [
                            {
                                "type": "function_call_output",
                                "call_id": "call_1",
                                "output": "{}",
                            }
                        ],
                    },
                    fallback_budget,
                ),
            ),
            patch.object(
                adapter,
                "build_summarization_followup_params",
                return_value={
                    "model": "gpt-4o-mini",
                    "prev_response_id": "resp_1",
                    "function_call_outputs": [{"id": "call_1", "output": "{}"}],
                    "max_output_tokens": 128,
                },
            ),
        ):
            adapter.call_responses_api(
                [{"role": "user", "content": "say hi"}],
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        assert fake_client.responses.create.call_count == 2
        summary_kwargs = fake_client.responses.create.call_args_list[1].kwargs
        assert summary_kwargs["previous_response_id"] == "resp_1"
        assert "tools" not in summary_kwargs
        assert isinstance(summary_kwargs["input"], list)
        assert any(
            isinstance(item, dict) and item.get("type") == "function_call_output"
            for item in summary_kwargs["input"]
        )

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch(
        "monitor.core.llm_responses_adapter.token_budgeter",
        side_effect=lambda params, *_args, **_kwargs: params,
    )
    @patch(
        "monitor.core.llm_responses_adapter.truncate_to_token_limit",
        side_effect=lambda s, *_args, **_kwargs: s,
    )
    @patch(
        "monitor.core.llm_responses_adapter.serialize_tool_output",
        side_effect=lambda obj: "{}",
    )
    @patch(
        "monitor.core.llm_responses_adapter.execute_tool_call",
        return_value=({"ok": True}, None),
    )
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    def test_call_responses_api_clears_response_id_after_followup_failure(
        self,
        _mock_get_tools,
        _mock_execute_tool_call,
        _mock_serialize,
        _mock_truncate,
        _mock_budgeter,
        mock_progress_dots,
    ):
        """Clear RESPONSE_ID when tool follow-up submission fails.

        Asserts:
            - The initial response id is persisted before the follow-up attempt.
            - A failed follow-up raises to the caller.
            - RESPONSE_ID is cleared so later requests start fresh.
        """
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
            output=[
                {
                    "type": "function_call",
                    "id": "call_1",
                    "name": "tools.echo",
                    "arguments": '{"x":1}',
                }
            ],
        )
        fake_client.responses.create.side_effect = [
            first,
            RuntimeError("follow-up denied"),
        ]

        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            TEMPERATURE=None,
            TOP_P=None,
            FREQUENCY_PENALTY=None,
            PRESENCE_PENALTY=None,
            MAX_COMPLETION_TOKENS=None,
            RATE_LIMITER=False,
            MODEL_INPUT_WINDOW=None,
            TOOL_OUTPUT_TOKEN_LIMIT=1_000,
        )

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            adapter.call_responses_api(
                [{"role": "user", "content": "say hi"}],
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        assert fake_client.responses.create.call_count == 2
        summary_kwargs = fake_client.responses.create.call_args_list[1].kwargs
        assert summary_kwargs.get("previous_response_id") == "resp_1"
        assert cfg.RESPONSE_ID == "resp_1"

    @patch("monitor.core.llm_responses_adapter.logger")
    @patch(
        "monitor.core.llm_responses_adapter.measure_followup_request_reserves",
        return_value={
            "tool_schema_reserve_tokens": 111,
            "structured_payload_reserve_tokens": 222,
        },
    )
    @patch(
        "monitor.core.llm_responses_adapter.count_serialized_structure_tokens",
        return_value=4321,
    )
    @patch("monitor.core.llm_responses_adapter.count_message_tokens", return_value=1234)
    def test_call_responses_api_logs_context_budget_debug_on_context_length_error(
        self,
        _mock_count_tokens,
        _mock_count_structural,
        _mock_measure_reserves,
        mock_logger,
    ):
        """Verify context-length failures emit reserve-aware diagnostics."""
        from monitor.core import llm_responses_adapter as adapter

        class FakeBadRequestError(Exception):
            """Provider-shaped bad request for testing."""

            def __init__(self, message, code):
                super().__init__(message)
                self.code = code

        fake_client = self.FakeClient()
        fake_client.responses.create.side_effect = FakeBadRequestError(
            "context too large",
            "context_length_exceeded",
        )

        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID="resp_prev",
            TURN_ROUND_TRIPS=[30],
            TEMPERATURE=None,
            TOP_P=None,
            FREQUENCY_PENALTY=None,
            PRESENCE_PENALTY=None,
            MAX_COMPLETION_TOKENS=None,
            RATE_LIMITER=False,
            MODEL_INPUT_WINDOW=10_000,
            MODEL_CONTEXT_WINDOW=None,
            FOLLOWUP_BASE_SAFETY_RATIO=0.85,
            FOLLOWUP_TOPLEVEL_RESERVE_TOKENS=256,
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS={
                "fresh_request": 0,
                "chained_user_followup": 2000,
                "tool_result_followup": 4000,
                "summarization_followup": 2000,
            },
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH=1000,
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO=0.5,
        )

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            with self.assertRaises(FakeBadRequestError):
                adapter.call_responses_api(
                    [{"role": "user", "content": "say hi"}],
                    tool_descriptions=[
                        {
                            "type": "function",
                            "function": {
                                "name": "echo",
                                "parameters": {
                                    "type": "object",
                                    "properties": {},
                                },
                            },
                        }
                    ],
                    gemini_tool_descriptions={},
                )

        assert any(
            call_args.args
            and "Responses API context window exceeded" in call_args.args[0]
            for call_args in mock_logger.error.call_args_list
        )
        error_exc = next(
            call_args.args[-1]
            for call_args in mock_logger.error.call_args_list
            if call_args.args
            and "Responses API context window exceeded" in call_args.args[0]
        )
        assert isinstance(error_exc, FakeBadRequestError)

        mock_logger.info.assert_any_call(
            "Responses API context debug payload: %s",
            ANY,
        )
        debug_payload_arg = next(
            call_args.args[1]
            for call_args in mock_logger.info.call_args_list
            if call_args.args
            and call_args.args[0] == "Responses API context debug payload: %s"
        )
        debug_payload = json.loads(debug_payload_arg)
        assert debug_payload["model"] == "gpt-4o-mini"
        assert debug_payload["request_class"] == "chained_user_followup"
        assert debug_payload["previous_response_id"] == "resp_prev"
        assert debug_payload["tool_count"] == 0
        assert debug_payload["input_text_tokens"] == 1234
        assert debug_payload["input_serialized_tokens"] == 4321
        assert debug_payload["tool_schema_reserve_tokens"] == 111
        assert debug_payload["structured_payload_reserve_tokens"] == 222
        assert debug_payload["model_input_window"] == 10_000
        assert debug_payload["usable_window"] == 8_500
        assert debug_payload["hidden_chain_reserve"] == 4_400
        assert debug_payload["top_level_reserve"] == 256
        assert debug_payload["payload_budget"] == 3_511
        assert debug_payload["decision"] == "send"


    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    @patch(
        "monitor.core.llm_responses_adapter.serialize_tool_output",
        side_effect=lambda obj: "{}",
    )
    @patch(
        "monitor.core.llm_responses_adapter.truncate_to_token_limit",
        side_effect=lambda s, *_args, **_kwargs: s,
    )
    @patch("monitor.core.llm_responses_adapter.execute_tool_call", return_value=({"ok": True}, None))
    def test_tool_followup_context_length_error_rebases_to_fresh_request(
        self,
        _mock_execute_tool_call,
        _mock_truncate,
        _mock_serialize,
        mock_rate_limiter,
        _mock_update_token_usage,
        _mock_get_tools,
        mock_progress_dots,
    ):
        """Rebase tool follow-up onto a fresh request when the provider rejects the chain."""
        from monitor.core import llm_responses_adapter as adapter

        class _DummyCtx:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeBadRequestError(Exception):
            """Provider-shaped bad request for testing."""

            def __init__(self, message, code):
                super().__init__(message)
                self.code = code

        def _build_response(response_id, output):
            return SimpleNamespace(id=response_id, output=output, usage={"total_tokens": 10})

        mock_progress_dots.return_value = _DummyCtx()
        mock_rate_limiter.RATE_LIMITER = None
        fake_client = self.FakeClient()
        fake_client.responses.create.side_effect = [
            _build_response(
                "resp_1",
                [
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "echo",
                        "arguments": "{}",
                    }
                ],
            ),
            FakeBadRequestError("context too large", "context_length_exceeded"),
            _build_response(
                "resp_2",
                [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "recovered"}],
                    }
                ],
            ),
        ]
        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            TURN_ROUND_TRIPS=[],
            TEMPERATURE=None,
            TOP_P=None,
            FREQUENCY_PENALTY=None,
            PRESENCE_PENALTY=None,
            MAX_COMPLETION_TOKENS=None,
            RATE_LIMITER=False,
            MODEL_INPUT_WINDOW=272_000,
            MODEL_CONTEXT_WINDOW=None,
            FOLLOWUP_BASE_SAFETY_RATIO=0.85,
            FOLLOWUP_TOPLEVEL_RESERVE_TOKENS=256,
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS={
                "fresh_request": 0,
                "chained_user_followup": 2000,
                "tool_result_followup": 4000,
                "summarization_followup": 2000,
            },
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH=1000,
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO=0.5,
        )

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            response = adapter.call_responses_api(
                [{"role": "user", "content": "say hi"}],
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        assert response["id"] == "resp_2"
        assert cfg.RESPONSE_ID == "resp_2"
        assert fake_client.responses.create.call_count == 3

        first_kwargs = fake_client.responses.create.call_args_list[0].kwargs
        second_kwargs = fake_client.responses.create.call_args_list[1].kwargs
        third_kwargs = fake_client.responses.create.call_args_list[2].kwargs

        assert "previous_response_id" not in first_kwargs
        assert second_kwargs["previous_response_id"] == "resp_1"
        assert isinstance(second_kwargs["input"], list)
        assert "previous_response_id" not in third_kwargs
        assert third_kwargs["input"] == [{"role": "user", "content": "say hi"}]

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    def test_call_responses_api_context_retry_starts_fresh_chain(
        self,
        mock_rate_limiter,
        _mock_update,
        _mock_get_tools,
        mock_progress_dots,
    ):
        """Retrying after context exhaustion should not reuse the old response chain."""
        from monitor.core import llm_responses_adapter as adapter

        class _DummyCtx:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeBadRequestError(Exception):
            """Provider-shaped bad request for testing."""

            def __init__(self, message, code):
                super().__init__(f"{message} ({code})")
                self.code = code

        mock_progress_dots.return_value = _DummyCtx()

        fake_client = self.FakeClient()
        fake_client.responses.create.side_effect = [
            FakeBadRequestError("context too large", "context_length_exceeded"),
            self._fake_response("resp_2", total_tokens=1, output=[]),
        ]

        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID="resp_stale",
            RATE_LIMITER=True,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        messages = [{"role": "user", "content": "new prompt after failure"}]

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            adapter.call_responses_api(
                messages,
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        assert fake_client.responses.create.call_count == 2
        first_kwargs = fake_client.responses.create.call_args_list[0].kwargs
        retry_kwargs = fake_client.responses.create.call_args_list[1].kwargs
        assert first_kwargs["previous_response_id"] == "resp_stale"
        assert retry_kwargs["input"] == messages
        assert "previous_response_id" not in retry_kwargs
        assert cfg.RESPONSE_ID == "resp_2"

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    def test_context_length_exceeded_returns_user_friendly_error(self, mock_progress_dots):
        """Verify context-length failures are converted into a friendly error message."""
        from monitor.core import llm_responses_adapter as adapter

        class _DummyCtx:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeBadRequestError(Exception):
            """Provider-shaped bad request for testing."""

            def __init__(self, message, code):
                super().__init__(message)
                self.code = code

        mock_progress_dots.return_value = _DummyCtx()
        fake_client = self.FakeClient()
        fake_client.responses.create.side_effect = FakeBadRequestError(
            "context too large",
            "context_length_exceeded",
        )
        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
        )

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            response, error_message = adapter.response_completion(
                "hello",
                tool_descriptions=[],
                gemini_tool_descriptions=[],
            )

        assert response is None
        assert "model context window" in error_message
        assert "shorten the conversation" in error_message
        assert "retry with compacted history" in error_message

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    def test_call_responses_api_starts_fresh_after_response_id_cleared(
        self,
        mock_rate_limiter,
        _mock_update,
        _mock_get_tools,
        mock_progress_dots,
    ):
        """Start a fresh request when RESPONSE_ID has been cleared after failure.

        Asserts:
            - No previous_response_id is sent.
            - The full prepared messages list is used as input.
        """
        from monitor.core import llm_responses_adapter as adapter

        class _DummyCtx:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc, tb):
                return False

        mock_progress_dots.return_value = _DummyCtx()

        fake_client = self.FakeClient()
        fake_client.responses.create.return_value = self._fake_response(
            "resp_fresh",
            total_tokens=1,
            output=[],
        )

        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            RATE_LIMITER=True,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        messages = [{"role": "user", "content": "new prompt after failure"}]

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            adapter.call_responses_api(
                messages,
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        kwargs = fake_client.responses.create.call_args.kwargs
        assert kwargs["model"] == "gpt-4o-mini"
        assert kwargs["input"] == messages
        assert "previous_response_id" not in kwargs

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
        fake_client.responses.create.return_value = self._fake_response(
            "resp_X",
            total_tokens=1,
            output=[],
        )

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
            adapter.call_responses_api(
                messages,
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        # Ensure only the latest user text was sent as the input string
        kwargs = fake_client.responses.create.call_args.kwargs
        assert kwargs["model"] == "gpt-4o-mini"
        assert kwargs["previous_response_id"] == "prev_123"
        assert isinstance(kwargs["input"], str)
        assert kwargs["input"] == "latest user input"

    @patch("monitor.core.llm_responses_adapter.call_responses_api")
    @patch(
        "monitor.core.llm_responses_adapter.prepare_response_messages",
        return_value=[{"role": "user", "content": "x"}],
    )
    @patch("monitor.core.llm_responses_adapter.estimate_response_tokens", return_value=60)
    def test_response_completion_uses_followup_base_safety_ratio_for_input_gate(
        self,
        _mock_estimate,
        _mock_prepare,
        mock_call_api,
    ):
        from monitor.core import llm_responses_adapter as adapter

        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            MODEL_INPUT_WINDOW=100,
            MODEL_CONTEXT_WINDOW=None,
            FOLLOWUP_BASE_SAFETY_RATIO=0.5,
            REASONING_MAX_COMPLETION_TOKENS=0,
            REASONING_MODEL_PREFIX="openai/o3",
            RATE_LIMITER=False,
        )
        with patch.object(adapter, "config", cfg):
            response, error = adapter.response_completion(
                "hello",
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        assert response is None
        assert "effective input window 50" in error
        mock_call_api.assert_not_called()

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
        fake_client.responses.create.return_value = self._fake_response(
            "resp_1",
            total_tokens=1,
            output=[],
        )
        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            RATE_LIMITER=True,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            adapter.call_responses_api(
                [{"role": "user", "content": "hello"}],
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        kwargs = fake_client.responses.create.call_args.kwargs
        assert kwargs["model"] == "gpt-4o-mini"
        assert kwargs.get("tools") == ["t"]
        assert kwargs.get("tool_choice") == "auto"

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch(
        "monitor.core.llm_responses_adapter.token_budgeter",
        side_effect=lambda params, *_args, **_kwargs: params,
    )
    @patch(
        "monitor.core.llm_responses_adapter.truncate_to_token_limit",
        side_effect=lambda s, *_args, **_kwargs: s,
    )
    @patch(
        "monitor.core.llm_responses_adapter.serialize_tool_output",
        side_effect=lambda obj: "{}",
    )
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

        fake_client = self.FakeClient()
        first = self._fake_response(
            "resp_1",
            total_tokens=2,
            output=[
                {
                    "type": "function_call",
                    "id": "call_1",
                    "name": "tools.echo",
                    "arguments": '{"a":1}',
                }
            ],
        )
        second = self._fake_response("resp_2", total_tokens=1, output=[])
        fake_client.responses.create.side_effect = [first, second]

        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            RATE_LIMITER=True,
            TEMPERATURE=None,
            TOP_P=None,
            FREQUENCY_PENALTY=None,
            PRESENCE_PENALTY=None,
            MAX_COMPLETION_TOKENS=None,
            MODEL_INPUT_WINDOW=None,
            TOOL_OUTPUT_TOKEN_LIMIT=8_192,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()
        mock_execute_tool_call.return_value = ({"ok": True}, None)

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            adapter.call_responses_api(
                [{"role": "user", "content": "hello"}],
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        mock_execute_tool_call.assert_called_once()
        called_args, _called_kwargs = mock_execute_tool_call.call_args
        assert isinstance(called_args[0], dict)
        assert called_args[0]["function"]["arguments"] == {"a": 1}

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch(
        "monitor.core.llm_responses_adapter.token_budgeter",
        side_effect=lambda params, *_args, **_kwargs: params,
    )
    @patch(
        "monitor.core.llm_responses_adapter.truncate_to_token_limit",
        side_effect=lambda s, *_args, **_kwargs: s,
    )
    @patch(
        "monitor.core.llm_responses_adapter.serialize_tool_output",
        side_effect=lambda obj: "{}",
    )
    @patch("monitor.core.llm_responses_adapter.execute_tool_call")
    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.update_token_usage")
    @patch("monitor.core.llm_responses_adapter.rate_limiter")
    @patch("monitor.core.llm_responses_adapter.activity.suspend_paint")
    @patch("monitor.core.llm_responses_adapter.activity.show")
    def test_responses_tool_loop_emits_activity_feedback(
        self,
        mock_activity_show,
        mock_suspend_paint,
        mock_rate_limiter,
        _mock_update_tokens,
        _mock_get_tools,
        mock_execute_tool_call,
        _mock_serialize,
        _mock_truncate,
        _mock_budgeter,
        mock_progress_dots,
    ):
        """Responses API tool execution should surface live activity like Chat path."""
        from monitor.core import llm_responses_adapter as adapter
        from monitor.lib import activity

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
            output=[
                {
                    "type": "function_call",
                    "id": "call_1",
                    "name": "run_python_tests",
                    "arguments": "{}",
                }
            ],
        )
        second = self._fake_response("resp_2", total_tokens=1, output=[])
        fake_client.responses.create.side_effect = [first, second]

        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            RATE_LIMITER=True,
            TEMPERATURE=None,
            TOP_P=None,
            FREQUENCY_PENALTY=None,
            PRESENCE_PENALTY=None,
            MAX_COMPLETION_TOKENS=None,
            MODEL_INPUT_WINDOW=272_000,
            MODEL_CONTEXT_WINDOW=None,
            FOLLOWUP_BASE_SAFETY_RATIO=0.85,
            FOLLOWUP_TOPLEVEL_RESERVE_TOKENS=256,
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS={
                "fresh_request": 0,
                "chained_user_followup": 2000,
                "tool_result_followup": 4000,
                "summarization_followup": 2000,
            },
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH=1000,
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO=0.5,
            TOOL_OUTPUT_TOKEN_LIMIT=8_192,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()
        mock_execute_tool_call.return_value = ({"ok": True}, None)

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            adapter.call_responses_api(
                [{"role": "user", "content": "hello"}],
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        mock_activity_show.assert_any_call(
            activity.STATE_RUNNING,
            rt_count=1,
            tool="run_python_tests",
        )
        mock_suspend_paint.assert_called_once()
        mock_activity_show.assert_any_call(
            activity.STATE_WAITING,
            rt_count=2,
        )

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch(
        "monitor.core.llm_responses_adapter.token_budgeter",
        side_effect=lambda params, *_args, **_kwargs: params,
    )
    @patch(
        "monitor.core.llm_responses_adapter.serialize_tool_output",
        side_effect=lambda obj: "{}",
    )
    @patch(
        "monitor.core.llm_responses_adapter.execute_tool_call",
        return_value=({"ok": True}, None),
    )
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
            output=[
                {
                    "type": "function_call",
                    "id": "call_1",
                    "name": "tools.echo",
                    "arguments": '{"x":1}',
                }
            ],
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

        with (
            patch.object(adapter, "client", fake_client),
            patch.object(adapter, "config", cfg),
            patch.object(
                adapter,
                "truncate_to_token_limit",
                return_value="{}",
            ) as mock_truncate,
        ):
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
        fake_client.responses.create.return_value = self._fake_response(
            "resp_1",
            total_tokens=None,
            output=[],
        )
        cfg = SimpleNamespace(
            MODEL="openai/gpt-4o-mini",
            RESPONSES_API=True,
            RESPONSE_ID=None,
            RATE_LIMITER=True,
        )
        mock_rate_limiter.RATE_LIMITER = MagicMock()

        with patch.object(adapter, "client", fake_client), patch.object(adapter, "config", cfg):
            adapter.call_responses_api(
                [{"role": "user", "content": "tokenless"}],
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        # update_token_usage should be called with 0
        mock_update_tokens.assert_any_call(
            0,
            used_estimate=True,
            response=ANY,
            model="openai/gpt-4o-mini",
        )

        # Rate limiter should receive an add_request with 0
        calls = mock_rate_limiter.RATE_LIMITER.add_request.call_args_list
        assert any(
            (len(c.args) > 0 and c.args[0] == 0)
            or (len(c.kwargs) > 0 and next(iter(c.kwargs.values())) == 0)
            for c in calls
        ), "Expected add_request to be called with 0 tokens"

    @patch("monitor.core.llm_responses_adapter.progress_dots")
    @patch(
        "monitor.core.llm_responses_adapter.token_budgeter",
        side_effect=lambda params, *_args, **_kwargs: params,
    )
    @patch(
        "monitor.core.llm_responses_adapter.truncate_to_token_limit",
        side_effect=Exception("truncate fail"),
    )
    @patch(
        "monitor.core.llm_responses_adapter.serialize_tool_output",
        side_effect=Exception("serialize fail"),
    )
    @patch(
        "monitor.core.llm_responses_adapter.execute_tool_call",
        return_value=({"ok": True}, None),
    )
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
            output=[
                {
                    "type": "function_call",
                    "id": "c1",
                    "name": "tools.echo",
                    "arguments": '{"a":1}',
                }
            ],
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
            adapter.call_responses_api(
                [{"role": "user", "content": "hi"}],
                tool_descriptions={},
                gemini_tool_descriptions={},
            )

        # Second call is the follow-up; verify payload output is the fallback string
        second_kwargs = fake_client.responses.create.call_args_list[1].kwargs
        assert isinstance(second_kwargs["input"], list)
        assert second_kwargs["input"][0]["output"] == adapter.SERIALIZATION_FAILED_STR

    @patch("monitor.core.llm_responses_adapter.get_tools_for_model", return_value=([], None))
    @patch("monitor.core.llm_responses_adapter.progress_dots")
    def test_client_lazy_configuration_failure(self, _mock_progress, _mock_get_tools):
        from monitor.core import llm_responses_adapter as adapter

        fake_client = None
        cfg = SimpleNamespace(MODEL="openai/gpt-4o-mini", RESPONSES_API=True)
        with (
            patch.object(adapter, "client", fake_client),
            patch.object(adapter, "config", cfg),
            patch.object(
                adapter,
                "configure_responses_adapter",
                side_effect=Exception("boom"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                adapter.call_responses_api(
                    [{"role": "user", "content": "x"}],
                    tool_descriptions={},
                    gemini_tool_descriptions={},
                )


if __name__ == "__main__":
    unittest.main()
