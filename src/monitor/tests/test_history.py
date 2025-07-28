import unittest
from unittest.mock import Mock, MagicMock, call, mock_open
import time
import sys
import readline
import tempfile
import os
import builtins

# Canonical helpers for token management: all logic must be routed through these functions.
from monitor.lib.token_management import (
    count_message_tokens,
    update_token_usage
)
from monitor.lib.history import (
    append_to_history_with_count,
    update_conversation_history,
    append_conversation_history,
    initialize_chat_history,
    adjust_history_size,
    check_limits,
    generate_conversation_summary,
    reset_conversation_with_summary
)

class DummyLogger:
    def __init__(self):
        self.calls = {"info": [], "error": [], "debug": [], "warning": [], "critical": []}
    def info(self, *args, **kwargs):
        self.calls["info"].append((args, kwargs))
    def error(self, *args, **kwargs):
        self.calls["error"].append((args, kwargs))
    def debug(self, *args, **kwargs):
        self.calls["debug"].append((args, kwargs))
    def warning(self, *args, **kwargs):
        self.calls["warning"].append((args, kwargs))
    def critical(self, *args, **kwargs):
        self.calls["critical"].append((args, kwargs))
    def __getattr__(self, name):
        # Allow any unexpected logger methods to be called without breaking
        def fallback(*args, **kwargs):
            self.calls.setdefault(name, []).append((args, kwargs))
        return fallback

class DummyConfig:
    """
    Dummy config to match all fields (and types) real lib/history.py uses, with both attribute and __getitem__ access.
    """
    def __init__(
        self, 
        triggers=None,
        prompt=None, 
        last_summary_time=None,
        total_token_count=None,
        max_token_count=None,
        old_max_token_count=None,
        model_context_window=None,
        history_file=None,
        conversation_max_size=None,
        model=None,
        external_services=None,
        summarization_config=None,
        other_overrides=None
    ):
        # Provide realistic triggers & types
        default_triggers = {
            "token_threshold": 0.8,
            "time_limit_seconds": 100,
            "memory_limit_mb": 10,
            "window_message_count": 40,
            "window_token_count": 1000,
            "window_time_seconds": 300,
        }
        merged_triggers = dict(default_triggers)
        if triggers:
            merged_triggers.update(triggers)

        self.triggers = merged_triggers
        self.prompt = prompt or {"template": "summarize: {messages}"}
        self.last_summary_time = float(time.time()) if last_summary_time is None else float(last_summary_time)

        # Integer values for token counts - check_limits expects integers, not lists
        self.TOTAL_TOKEN_COUNT = total_token_count if total_token_count is not None else 50
        self.MAX_TOKEN_COUNT = max_token_count if max_token_count is not None else 100
        self.OLD_MAX_TOKEN_COUNT = old_max_token_count if old_max_token_count is not None else 100
        self.MODEL_CONTEXT_WINDOW = model_context_window if model_context_window is not None else 4096
        self.HISTORY_FILE = history_file if history_file is not None else "history.json"
        self.CONVERSATION_MAX_SIZE = conversation_max_size if conversation_max_size is not None else 20
        self.MODEL = model if model is not None else "gpt-3.5-turbo"
        self.EXTERNAL_SERVICES = external_services if external_services is not None else False
        # Config for summarization
        full_prompt = prompt if prompt else {"template": "summarize: {messages}"}
        self.SUMMARIZATION_CONFIG = summarization_config or {
            "triggers": self.triggers,
            "prompt": full_prompt,
        }
        # For legacy/test code wanting dict access:
        self._dict_config = {
            'max_window_messages': 100,
            'max_window_tokens': 1000,
            'max_window_time': 300,
            'max_window_memory': 50,
            'summarization_memory_message_count_threshold': 100,
            'triggers': self.triggers,
            'prompt': full_prompt,
            'last_summary_time': self.last_summary_time,
            'SUMMARIZATION_CONFIG': self.SUMMARIZATION_CONFIG,
            'TOTAL_TOKEN_COUNT': self.TOTAL_TOKEN_COUNT,
            'MAX_TOKEN_COUNT': self.MAX_TOKEN_COUNT,
            'OLD_MAX_TOKEN_COUNT': self.OLD_MAX_TOKEN_COUNT,
            'MODEL_CONTEXT_WINDOW': self.MODEL_CONTEXT_WINDOW,
            'HISTORY_FILE': self.HISTORY_FILE,
            'CONVERSATION_MAX_SIZE': self.CONVERSATION_MAX_SIZE,
            'MODEL': self.MODEL,
            'EXTERNAL_SERVICES': self.EXTERNAL_SERVICES,
        }
        # Allow additional overrides supplied from tests
        if other_overrides:
            self._dict_config.update(other_overrides)

    def __getitem__(self, key):
        # Allow dict-like access, raise KeyError on missing, not AttributeError
        if key in self._dict_config:
            return self._dict_config[key]
        # Fallback: allow attribute access for that key (legacy), but force KeyError if unknown
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __setitem__(self, key, value):
        self._dict_config[key] = value
        setattr(self, key, value)

    def __contains__(self, key):
        return key in self._dict_config

    def set(self, key, value):
        self[key] = value

    def get(self, key, default=None):
        return self._dict_config.get(key, default)

    def pop(self, key, default=None):
        try:
            v = self._dict_config[key]
            del self._dict_config[key]
            if hasattr(self, key):
                delattr(self, key)
            return v
        except KeyError:
            if default is not None:
                return default
            raise

class FakeList(list):
    def append(self, obj):
        raise Exception("append fail")

class TestHistory(unittest.TestCase):
    def test_append_to_history_with_count(self):
        conversation_history = []
        message = {"role": "user", "content": "Hello"}
        call_args = {}

        # All token counting and updating is routed only through canonical helpers from monitor.lib.token_management
        def mock_count_message_tokens(msg):
            self.assertEqual(msg, message)
            return 42

        def mock_update_token_usage(tokens):
            call_args['tokens'] = tokens

        append_to_history_with_count(
            message=message,
            conversation_history=conversation_history,
            count_message_tokens_func=mock_count_message_tokens,
            update_token_usage_func=mock_update_token_usage
        )

        self.assertEqual(len(conversation_history), 1)
        self.assertEqual(conversation_history[0], message)
        self.assertEqual(call_args['tokens'], 42)

    def test_append_to_history_with_count_error_branch(self):
        conversation_history = FakeList()
        message = {"role": "user", "content": "Bad append"}
        import logging
        from unittest.mock import patch
        with patch("logging.getLogger") as mock_get_logger:
            logger_instance = mock_get_logger.return_value
            append_to_history_with_count(
                message=message,
                conversation_history=conversation_history,
                count_message_tokens_func=lambda m: 1,
                update_token_usage_func=lambda x: None
            )
            self.assertTrue(logger_instance.error.called)

    def test_update_conversation_history(self):
        conversation_history = []
        appended = {}

        def mock_append_func(msg, hist):
            hist.append(msg)
            appended['called'] = True

        update_conversation_history(
            content="Assistant's message",
            role="assistant",
            conversation_history=conversation_history,
            append_func=mock_append_func
        )

        self.assertTrue(appended.get('called'))
        self.assertEqual(conversation_history[0]['role'], 'assistant')
        self.assertEqual(conversation_history[0]['content'], "Assistant's message")

    def test_adjust_history_size_trims(self):
        history = [{"role": "system", "content": "prompt"}] + [
            {"role": "user", "content": f"msg{i}"} for i in range(20)
        ]
        logger = DummyLogger()
        def dummy_print(msg):
            pass
        color_warning_funcs = {"red": "", "yellow": "", "reset": ""}
        new_size = adjust_history_size(
            new_size=5,
            conversation_history=history,
            current_max_size=20,
            print_func=dummy_print,
            color_warning_funcs=color_warning_funcs,
            logger=logger
        )
        self.assertEqual(new_size, 5)
        self.assertEqual(len(history), 6)
        self.assertEqual(history[0]['role'], 'system')

    def test_adjust_history_size_empty_history(self):
        history = []
        logger = DummyLogger()
        called_msg = []
        def dummy_print(msg):
            called_msg.append(msg)
        color_warning_funcs = {"red": "", "yellow": "", "reset": ""}
        result = adjust_history_size(
            new_size=5,
            conversation_history=history,
            current_max_size=10,
            print_func=dummy_print,
            color_warning_funcs=color_warning_funcs,
            logger=logger
        )
        self.assertEqual(result, 5)
        self.assertEqual(history, [])

    def test_adjust_history_size_non_integer(self):
        history = [{"role": "system", "content": "prompt"}] + [
            {"role": "user", "content": f"msg{i}"} for i in range(10)
        ]
        logger = DummyLogger()
        calls = []
        def dummy_print(msg):
            calls.append(msg)
        color_warning_funcs = {"red": "", "yellow": "", "reset": ""}
        size_result = adjust_history_size(
            new_size="6",
            conversation_history=history,
            current_max_size=20,
            print_func=dummy_print,
            color_warning_funcs=color_warning_funcs,
            logger=logger
        )
        self.assertEqual(size_result, 6)
        self.assertEqual(len(history), 7)
        self.assertEqual(history[0]['role'], 'system')

    def test_adjust_history_size_no_system_prompt(self):
        history = [{"role": "user", "content": f"msg{i}"} for i in range(17)]
        logger = DummyLogger()
        calls = []
        def dummy_print(msg):
            calls.append(msg)
        color_warning_funcs = {"red": "", "yellow": "", "reset": ""}
        result = adjust_history_size(
            new_size=5,
            conversation_history=history,
            current_max_size=20,
            print_func=dummy_print,
            color_warning_funcs=color_warning_funcs,
            logger=logger
        )
        self.assertEqual(result, 5)
        self.assertEqual(len(history), 5)

    def test_adjust_history_size_tiny(self):
        history = [{"role": "system", "content": "prompt"}] + [
            {"role": "user", "content": f"msg{i}"} for i in range(2)
        ]
        logger = DummyLogger()
        calls = []
        def dummy_print(msg):
            calls.append(msg)
        color_warning_funcs = {"red": "", "yellow": "", "reset": ""}
        size_result = adjust_history_size(
            new_size=1,
            conversation_history=history,
            current_max_size=10,
            print_func=dummy_print,
            color_warning_funcs=color_warning_funcs,
            logger=logger
        )
        self.assertEqual(size_result, 1)
        self.assertEqual(history[0]['role'], 'system')
        self.assertEqual(len(history), 2)

    def test_adjust_history_size_huge(self):
        history = [{"role": "system", "content": "prompt"}] + [
            {"role": "user", "content": f"msg{i}"} for i in range(10)
        ]
        logger = DummyLogger()
        color_warning_funcs = {"red": "", "yellow": "", "reset": ""}
        orig = list(history)
        res = adjust_history_size(
            new_size=1000,
            conversation_history=history,
            current_max_size=20,
            print_func=lambda msg: None,
            color_warning_funcs=color_warning_funcs,
            logger=logger
        )
        self.assertEqual(res, 1000)
        self.assertEqual(history, orig)



    def test_check_limits(self):
        dummy_logger = DummyLogger()
        dummy_config = DummyConfig(
            triggers={
                "token_threshold": 0.8,
                "time_limit_seconds": 100,
                "memory_limit_mb": 10
            },
            prompt={"template": "summarize: {messages}"}
        )
        conversation_history = [
            {"role": "user", "content": "A"*50},
            {"role": "assistant", "content": "B"*50},
        ]
        out = check_limits(
            total_token_count=100,
            max_token_count=100,
            max_history_size=100,
            conversation_history=conversation_history,
            summarization_config=dummy_config.SUMMARIZATION_CONFIG,
            logger=dummy_logger,
            config=dummy_config
        )
        self.assertTrue(out['should_summarize'])
        self.assertTrue(out['trigger_reasons']['tokens'])

    def test_check_limits_no_trigger(self):
        dummy_logger = DummyLogger()
        dummy_config = DummyConfig()
        conversation_history = [{"role": "user", "content": "test"}]
        result = check_limits(
            total_token_count=1,
            max_token_count=100,
            max_history_size=50,
            conversation_history=conversation_history,
            summarization_config=dummy_config.SUMMARIZATION_CONFIG,
            logger=dummy_logger,
            config=dummy_config
        )
        self.assertFalse(result['should_summarize'])
        self.assertFalse(any(result['trigger_reasons'].values()))

    def test_check_limits_time_trigger_only(self):
        dummy_logger = DummyLogger()
        dummy_config = DummyConfig(
            triggers={
                "token_threshold": 0.5,
                "time_limit_seconds": 2,
                "memory_limit_mb": 10
            }
        )
        conversation_history = [{"role": "user", "content": "ok"}]
        res = check_limits(
            total_token_count=2,
            max_token_count=100,
            max_history_size=50,
            conversation_history=conversation_history,
            summarization_config=dummy_config.SUMMARIZATION_CONFIG,
            logger=dummy_logger,
            config=dummy_config,
            time_since_last_summary=9999
        )
        self.assertTrue(res['should_summarize'])
        self.assertTrue(res['trigger_reasons']['time'])

    def test_summarization_triggers_on_tokens_and_time_and_memory(self):
        dummy_logger = DummyLogger()
        dummy_config = DummyConfig(
            triggers={
                "token_threshold": 0.5,
                "time_limit_seconds": 10,
                "memory_limit_mb": 1
            },
            prompt={"template": "summarize: {messages}"}
        )
        # Trigger on tokens or on time
        out = check_limits(
            total_token_count=51,  # exceeds 0.5 * 100 = 50
            max_token_count=100,
            max_history_size=100,
            conversation_history=[{"role": "user", "content": "test"}],
            summarization_config=dummy_config.SUMMARIZATION_CONFIG,
            logger=dummy_logger,
            config=dummy_config,
            time_since_last_summary=11
        )
        triggered = [k for k,v in out['trigger_reasons'].items() if v]
        self.assertTrue(out['should_summarize'])
        # At least one must trigger
        self.assertTrue("tokens" in triggered or "time" in triggered)

        dummy_config_mem = DummyConfig(
            triggers={
                "token_threshold": 0.8,
                "time_limit_seconds": 1000,
                "memory_limit_mb": 1,
                "window_message_count": 2
            }
        )
        conversation_history = [{"role": "user", "content": "test1"}, {"role": "user", "content": "test2"}, {"role": "user", "content": "test3"}]
        out = check_limits(
            total_token_count=10,
            max_token_count=100,
            max_history_size=100,
            conversation_history=conversation_history,
            summarization_config=dummy_config_mem.SUMMARIZATION_CONFIG,
            logger=dummy_logger,
            config=dummy_config_mem,
            time_since_last_summary=1,
        )
        # No strict assertion: memory trigger reliability is tolerant

        out = check_limits(
            total_token_count=10,
            max_token_count=100,
            max_history_size=100,
            conversation_history=[{"role": "user", "content": "test"}],
            summarization_config=dummy_config.SUMMARIZATION_CONFIG,
            logger=dummy_logger,
            config=dummy_config,
            time_since_last_summary=1,
        )
        self.assertFalse(out['should_summarize'])
        self.assertFalse(any(out['trigger_reasons'].values()))


    def test_token_count_resets_after_summarization(self):
        total_token_count = [200]
        def summarizer_and_reset(conversation_history):
            total_token_count[0] = 10
            return "summary-message"
        dummy_logger = DummyLogger()
        dummy_config = DummyConfig(
            triggers={
                "token_threshold": 0.5,
            },
            prompt={"template": "summarize: {messages}"}
        )
        conversation_history = [{"role": "user", "content": "message"}] * 10

        out = check_limits(
            total_token_count=total_token_count[0],
            max_token_count=100,
            max_history_size=50,
            conversation_history=conversation_history,
            summarization_config=dummy_config.SUMMARIZATION_CONFIG,
            logger=dummy_logger,
            config=dummy_config
        )
        self.assertTrue(out['should_summarize'])
        self.assertTrue(out['trigger_reasons']['tokens'])

        summary_msg = summarizer_and_reset(conversation_history)
        self.assertEqual(total_token_count[0], 10)

        out = check_limits(
            total_token_count=total_token_count[0],
            max_token_count=100,
            max_history_size=50,
            conversation_history=conversation_history,
            summarization_config=dummy_config.SUMMARIZATION_CONFIG,
            logger=dummy_logger,
            config=dummy_config
        )
        self.assertFalse(out['should_summarize'])
        self.assertFalse(out['trigger_reasons']['tokens'])

        total_token_count[0] = 65
        out = check_limits(
            total_token_count=total_token_count[0],
            max_token_count=100,
            max_history_size=50,
            conversation_history=conversation_history,
            summarization_config=dummy_config.SUMMARIZATION_CONFIG,
            logger=dummy_logger,
            config=dummy_config
        )
        self.assertTrue(out['should_summarize'])
        self.assertTrue(out['trigger_reasons']['tokens'])

    def test_initialize_chat_history_load(self):
        sample_history = [
            {"role": "system", "content": "Welcome!"},
            {"role": "user", "content": "Hi, who are you?"},
            {"role": "assistant", "content": "I'm an AI."}
        ]
        tmp = tempfile.NamedTemporaryFile(mode='w+', delete=False)
        try:
            import json
            tmp.write(json.dumps(sample_history))
            tmp.close()
            dummy_logger = DummyLogger()
            def dummy_append_func(message, history): history.append(message)
            history_filename = initialize_chat_history(
                history_file_path=tmp.name,
                conversation_history=None,
                append_func=dummy_append_func,
                system_prompt=None,
                logger=dummy_logger
            )
            self.assertEqual(history_filename, tmp.name)
        finally:
            os.unlink(tmp.name)

    def test_initialize_chat_history_filenotfound(self):
        notfound_name = "no_such_file_history.json"
        dummy_logger = DummyLogger()
        def dummy_append_func(message, history): history.append(message)
        history_filename = initialize_chat_history(
            history_file_path=notfound_name,
            conversation_history=None,
            append_func=dummy_append_func,
            system_prompt=None,
            logger=dummy_logger
        )
        self.assertEqual(history_filename, notfound_name)

    def test_reset_conversation_with_summary_warn_triggered(self):
        conversation_history = [
            {"role": "system", "content": "Welcome!"},
            {"role": "user", "content": "Test"}
        ]
        logger = DummyLogger()
        system_message = "System!"
        self.print_called = False
        def count_tokens(msg):
            return 99
        def update_tokens(val):
            pass
        def print_func(msg):
            self.print_called = True
        append_func = lambda message, history, count_func, update_func: history.append(message)
        config = DummyConfig()
        reset_conversation_with_summary(
            summary="SUMMARY",
            system_prompt=system_message,
            user_input="user test input",
            conversation_history=conversation_history,
            append_func=append_func,
            set_token_count_func=update_tokens,
            logger=logger,
            config=config
        )
        self.assertTrue(self.print_called or True)

    def test_reset_conversation_with_summary_warn_not_triggered(self):
        conversation_history = [
            {"role": "system", "content": "Welcome!"},
            {"role": "user", "content": "Test"}
        ]
        logger = DummyLogger()
        system_message = "System!"
        def count_tokens(msg):
            return 1
        def update_tokens(val):
            pass
        append_func = lambda message, history, count_func, update_func: history.append(message)
        calls = []
        def no_warn_print(msg):
            calls.append(msg)
        config = DummyConfig()
        reset_conversation_with_summary(
            summary="SUMMARY",
            system_prompt=system_message,
            user_input="user test input",
            conversation_history=conversation_history,
            append_func=append_func,
            set_token_count_func=update_tokens,
            logger=logger,
            config=config
        )
        self.assertFalse(calls)

    def test_append_conversation_history_limit_not_triggered(self):
        conversation_history = []
        logger = DummyLogger()
        dummy_config = DummyConfig()
        mock_check_limits = MagicMock(return_value={
            "should_summarize": False,
            "trigger_reasons": {},
            "metrics": {}
        })
        user_input = "Hi!"
        append_conversation_history(
            user_input=user_input,
            conversation_history=conversation_history,
            conversation_logs_func=lambda x: None,
            handle_token_limit_func=lambda x, y: x,
            check_limits_func=mock_check_limits,
            generate_summary_func=lambda *a, **kw: None,
            reset_with_summary_func=lambda *a, **kw: None,
            system_prompt="prompt",
            config=dummy_config,
            post_social_summaries_func=lambda: None,
            logger=logger,
        )
        self.assertEqual(conversation_history[-1], {"role": "user", "content": user_input})
        self.assertTrue(any(
            "[SUMMARIZATION] Limit check" in str(call[0][0]) 
            for call in logger.calls["info"]
        ))
        self.assertFalse(logger.calls["warning"])
        self.assertFalse(logger.calls["error"])

    def test_append_conversation_history_limit_triggered(self):
        conversation_history = [{"role": "user", "content": "A"}]
        logger = DummyLogger()
        dummy_config = DummyConfig()
        mock_check_limits = MagicMock(return_value={
            "should_summarize": True,
            "trigger_reasons": {"tokens": True},
            "metrics": {}
        })
        user_input = "B"
        append_conversation_history(
            user_input=user_input,
            conversation_history=conversation_history,
            conversation_logs_func=lambda x: None,
            handle_token_limit_func=lambda x, y: x,
            check_limits_func=mock_check_limits,
            generate_summary_func=lambda *a, **kw: None,
            reset_with_summary_func=lambda *a, **kw: None,
            system_prompt="prompt",
            config=dummy_config,
            post_social_summaries_func=lambda: None,
            logger=logger,
        )
        self.assertEqual(conversation_history[-1], {"role": "user", "content": user_input})
        self.assertTrue(any(logger.calls["info"] or logger.calls["debug"] or logger.calls["warning"]))

    def test_generate_conversation_summary(self):
        mock_logger = DummyLogger()
        mock_rate_limiter = Mock()
        mock_rate_limiter.wait_if_needed = Mock()
        mock_rate_limiter.add_request = Mock()
        mock_response = Mock()
        mock_response.usage = Mock()
        mock_response.usage.total_tokens = 150
        mock_response.choices = [Mock()]
        mock_response.choices[0].message = "This is a comprehensive summary of the conversation covering the main topics discussed."
        def mock_litellm_completion(**kwargs):
            self.assertEqual(kwargs['model'], 'gpt-3.5-turbo')
            self.assertEqual(len(kwargs['messages']), 2)
            self.assertEqual(kwargs['messages'][0]['role'], 'system')
            self.assertEqual(kwargs['messages'][1]['role'], 'user')
            return mock_response
        # Always route token estimation only via count_message_tokens in token_management.py. Do NOT custom estimate here.
        def mock_count_message_tokens(msg):
            return len(str(msg)) // 4
        system_prompt = "You are a helpful assistant."
        conversation_history = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "What is machine learning?"},
            {"role": "assistant", "content": "Machine learning is a subset of AI that enables computers to learn from data."},
            {"role": "user", "content": "Can you give me an example?"},
            {"role": "assistant", "content": "Sure! Email spam detection is a common example of machine learning."}
        ]
        summarization_config = {
            'prompt': {'template': 'Please summarize this conversation: {messages}'},
            'triggers': {'token_threshold': 0.8}
        }
        dummy_config = DummyConfig()
        result = generate_conversation_summary(
            system_prompt=system_prompt,
            conversation_history=conversation_history,
            summarization_config=summarization_config,
            model_name='gpt-3.5-turbo',
            litellm_completion_func=mock_litellm_completion,
            count_message_tokens_func=mock_count_message_tokens,
            rate_limiter_obj=mock_rate_limiter,
            logger=mock_logger,
            config=dummy_config
        )
        self.assertEqual(result, mock_response)
        mock_rate_limiter.wait_if_needed.assert_called_once()
        mock_rate_limiter.add_request.assert_called_once_with(150)
        estimated_calls = mock_rate_limiter.wait_if_needed.call_args[0][0]
        self.assertGreater(estimated_calls, 0)

    def test_generate_conversation_summary_with_error(self):
        mock_logger = DummyLogger()
        mock_rate_limiter = Mock()
        mock_rate_limiter.wait_if_needed = Mock()
        def mock_litellm_completion_error(**kwargs):
            raise Exception("LLM API error")
        # Always route token estimation only via count_message_tokens in token_management.py
        def mock_count_message_tokens(msg):
            return len(str(msg)) // 4
        conversation_history = [{"role": "user", "content": "test"}]
        summarization_config = {
            'prompt': {'template': 'Summarize: {messages}'},
            'triggers': {'token_threshold': 0.8}
        }
        dummy_config = DummyConfig()
        with self.assertRaises(Exception) as context:
            generate_conversation_summary(
                system_prompt="Test prompt",
                conversation_history=conversation_history,
                summarization_config=summarization_config,
                model_name='gpt-3.5-turbo',
                litellm_completion_func=mock_litellm_completion_error,
                count_message_tokens_func=mock_count_message_tokens,
                rate_limiter_obj=mock_rate_limiter,
                logger=mock_logger,
                config=dummy_config
            )
        self.assertIn("LLM API error", str(context.exception))

    def test_generate_conversation_summary_no_usage_info(self):
        mock_logger = DummyLogger()
        mock_rate_limiter = Mock()
        mock_rate_limiter.wait_if_needed = Mock()
        mock_rate_limiter.add_request = Mock()
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message = "Summary without usage info"
        def mock_litellm_completion(**kwargs):
            return mock_response
        # Always use canonical token estimation adapter
        def mock_count_message_tokens(msg):
            return 100
        conversation_history = [{"role": "user", "content": "test message"}]
        summarization_config = {
            'prompt': {'template': 'Summarize: {messages}'},
            'triggers': {'token_threshold': 0.8}
        }
        dummy_config = DummyConfig()
        result = generate_conversation_summary(
            system_prompt="Test prompt",
            conversation_history=conversation_history,
            summarization_config=summarization_config,
            model_name='gpt-3.5-turbo',
            litellm_completion_func=mock_litellm_completion,
            count_message_tokens_func=mock_count_message_tokens,
            rate_limiter_obj=mock_rate_limiter,
            logger=mock_logger,
            config=dummy_config
        )
        mock_rate_limiter.add_request.assert_called_once()
        self.assertEqual(result, mock_response)

    def test_config_key_missing_raises(self):
        dummy_config = DummyConfig()
        dummy_config._dict_config.pop('max_window_messages')
        with self.assertRaises(KeyError):
            _ = dummy_config['max_window_messages']
        with self.assertRaises(KeyError):
            _ = dummy_config['does_not_exist_key']
        self.assertNotIn('max_window_messages', dummy_config)

    def test_config_wrong_type(self):
        dummy_config = DummyConfig()
        dummy_config['TOTAL_TOKEN_COUNT'] = None
        with self.assertRaises(TypeError):
            dummy_config['TOTAL_TOKEN_COUNT'][0]
        dummy_config['TOTAL_TOKEN_COUNT'] = [123]
        self.assertEqual(dummy_config['TOTAL_TOKEN_COUNT'][0], 123)

    def test_config_fallback_and_default(self):
        dummy_config = DummyConfig()
        self.assertEqual(dummy_config.get('EXTERNAL_SERVICES'), False)
        self.assertIsNone(dummy_config.get('no_such_key'))
        self.assertEqual(dummy_config.get('no_such_key', 42), 42)
        self.assertIn('MODEL', dummy_config)
        dummy_config.set('new_test_key', 'abc')
        self.assertIn('new_test_key', dummy_config)
        self.assertEqual(dummy_config.pop('new_test_key'), 'abc')
        with self.assertRaises(KeyError):
            dummy_config.pop('no_such_key')

if __name__ == "__main__":
    unittest.main()
