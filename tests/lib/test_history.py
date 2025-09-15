import pytest
from monitor.lib.history import update_conversation_history, append_to_history_with_count

def test_update_conversation_history_appends_message():
    conversation_history = []
    appended = {}

    def mock_count_message_tokens(msg):
        appended['counted'] = True
        return 3

    def mock_update_token_usage(tokens):
        appended['updated'] = True
        appended['tokens'] = tokens

    def mock_append_func(msg, hist, count_message_tokens_func, update_token_usage_func):
        tokens = count_message_tokens_func(msg)
        update_token_usage_func(tokens)
        hist.append(msg)
        appended['called'] = True

    update_conversation_history(
        content="Test assistant message",
        role="assistant",
        conversation_history=conversation_history,
        append_func=mock_append_func,
        count_message_tokens_func=mock_count_message_tokens,
        update_token_usage_func=mock_update_token_usage
    )

    assert len(conversation_history) == 1
    assert conversation_history[0]['role'] == "assistant"
    assert conversation_history[0]['content'] == "Test assistant message"
    assert appended['called']


def test_update_conversation_history_handles_none_content():
    conversation_history = []
    appended = {}
    def mock_append_func(msg, hist, count_message_tokens_func, update_token_usage_func):
        appended['called'] = True

    update_conversation_history(
        content=None,
        role="assistant",
        conversation_history=conversation_history,
        append_func=mock_append_func,
        count_message_tokens_func=lambda x: 0,
        update_token_usage_func=lambda x: None
    )
    # Should not call append_func on None content
    assert not appended.get('called', False)


def test_append_to_history_with_count_token_management():
    conversation_history = []
    tokens_logged = {}
    def update_token_usage(tokens):
        tokens_logged['tokens'] = tokens

    append_to_history_with_count(
        {'role': 'user', 'content': 'hello world'},
        conversation_history,
        lambda msg: 5,
        update_token_usage
    )
    assert conversation_history[0]['role'] == 'user'
    assert conversation_history[0]['content'] == 'hello world'
    assert tokens_logged['tokens'] == 5


def test_update_conversation_history_exception_logging(monkeypatch):
    conversation_history = []
    messages = []
    def bad_append_func(*args, **kwargs):
        raise ValueError("append failed!")
    called = {}
    class DummyLogger:
        def error(self, msg, **kwargs):
            called['error'] = msg
    monkeypatch.setattr('monitor.lib.history.logger', DummyLogger())

    update_conversation_history(
        content="problematic message",
        role="assistant",
        conversation_history=conversation_history,
        append_func=bad_append_func,
        count_message_tokens_func=lambda x: 0,
        update_token_usage_func=lambda x: None
    )
    assert 'error' in called
