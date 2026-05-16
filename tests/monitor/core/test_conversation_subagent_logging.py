import types
from unittest.mock import MagicMock, patch
import pytest
import os

import monitor.core.conversation as conversation
import monitor.config
from monitor.lib import subagent_logging


def test_conversation_triggers_subagent_logging(monkeypatch):
    # Mock the LLM initial completion to return a response-like object
    fake_message = types.SimpleNamespace(content="This is a reply")
    fake_choice = types.SimpleNamespace(message=fake_message)
    fake_response = types.SimpleNamespace(choices=[fake_choice])

    def fake_get_llm_initial_completion():
        return fake_response, None

    monkeypatch.setattr(conversation, "get_llm_initial_completion", fake_get_llm_initial_completion)

    # Patch append_interaction so no file IO occurs and we can assert it was called
    with patch("monitor.lib.subagent_logging.append_interaction") as mock_append:
        # Ensure MONITOR_AGENT env enables agent behavior
        monkeypatch.setenv("MONITOR_AGENT", "1")
        monitor.config.AGENT = True
        # Also patch process_response_by_type to a no-op to avoid deep processing
        monkeypatch.setattr(conversation, "process_response_by_type", lambda *a, **k: "OK")

        # Set monitor.config safeties to sensible defaults to avoid coercion errors
        monitor.config.MAX_TOKEN_COUNT = 100000
        monitor.config.CONVERSATION_HISTORY = []
        monitor.config.CONVERSATION_MAX_SIZE = 100
        monitor.config.TOTAL_TOKEN_COUNT = 0

        # Ensure SUMMARIZATION_CONFIG has a minimal triggers.token_threshold to avoid None subscripting
        monitor.config.SUMMARIZATION_CONFIG = {
            "triggers": {
                "token_threshold": 0.95,
                "time_limit_seconds": 3600,
                "memory_limit_mb": 100,
                "token_reduction_factor": 0.5,
                "safety_margin": 0.8,
            },
            "prompt_template": (
                "Summarize the conversation to retain essential information while reducing token usage. "
                "Preserve key facts, decisions, actions, and entities. Output a concise summary suitable "
                "for restoring context with minimal tokens."
            ),
        }

        result = conversation.query("Why is the sky blue?")

        # Ensure append_interaction was called with prompt and reply
        assert mock_append.called, "Expected append_interaction to be called when MONITOR_AGENT is set"
        args, kwargs = mock_append.call_args

        # Extract prompt and reply values safely from kwargs or positional args
        if "prompt_text" in kwargs:
            prompt = kwargs.get("prompt_text")
        elif len(args) >= 1:
            prompt = args[0]
        else:
            prompt = None

        if "reply_text" in kwargs:
            reply = kwargs.get("reply_text")
        elif len(args) >= 2:
            reply = args[1]
        else:
            reply = None

        assert prompt is not None and "Why is the sky blue" in prompt
        assert reply is not None and "This is a reply" in reply
