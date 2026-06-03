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


def test_append_to_history_with_count_appends_message_and_routes_through_history_counter(monkeypatch):
    """append_to_history_with_count no longer invokes the passed
    update_token_usage_func — that callable was being used to credit
    SESSION_TOTAL_TOKENS + LAST_REQUEST_TOKEN_COUNT on every local
    append, which inflated U: and L: with no actual API call.

    Now appends route through update_history_token_count (TOTAL_TOKEN_COUNT
    only). This test pins both behaviors: the message lands in history,
    and the legacy update_token_usage_func argument is no longer invoked.
    """
    from monitor.lib import token_management as tm

    conversation_history = []
    history_counter_calls = []
    monkeypatch.setattr(
        tm,
        "update_history_token_count",
        lambda n: history_counter_calls.append(n),
    )
    # Also rebind the module-level alias inside lib.history because the
    # function was imported by name there.
    from monitor.lib import history as history_mod
    monkeypatch.setattr(history_mod, "update_history_token_count",
                        lambda n: history_counter_calls.append(n))

    legacy_token_usage_called = {"count": 0}
    def legacy_update_token_usage(tokens):
        legacy_token_usage_called["count"] += 1

    append_to_history_with_count(
        {'role': 'user', 'content': 'hello world'},
        conversation_history,
        lambda msg: 5,
        legacy_update_token_usage,
    )

    assert conversation_history[0]['role'] == 'user'
    assert conversation_history[0]['content'] == 'hello world'
    # New path: history counter got the token count.
    assert history_counter_calls == [5]
    # Old path: passed callable is no longer invoked.
    assert legacy_token_usage_called["count"] == 0


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
