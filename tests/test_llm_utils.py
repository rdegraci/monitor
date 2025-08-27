import pytest

from monitor.lib import llm_utils
from monitor.lib.llm_utils import AttrDict, dict_to_attr, validate_tool_message_order, determine_response_type

class DummyChoice:
    def __init__(self, message=None, finish_reason=None):
        self.message = message
        self.finish_reason = finish_reason

class DummyMessage:
    def __init__(self, role='assistant', content=None, tool_calls=None, function_call=None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls
        self.function_call = function_call

class DummyResponse:
    def __init__(self, choices=None, usage=None):
        self.choices = choices or []
        self.usage = usage

class DummyUsage:
    def __init__(self, total_tokens):
        self.total_tokens = total_tokens

def test_attrdict_and_dict_to_attr():
    d = {'a': 1, 'b': {'c': 3}, 'lst': [{'x': 10}]}
    ad = dict_to_attr(d)
    assert hasattr(ad, 'a') and ad.a == 1
    assert hasattr(ad, 'b') and ad.b.c == 3
    assert isinstance(ad.lst, list) and ad.lst[0].x == 10


def test_validate_tool_message_order_valid_sequence():
    messages = [
        {'role': 'user', 'content': 'hi'},
        {'role': 'assistant', 'content': 'calling tool', 'tool_calls': [{'id': 't1'}]},
        {'role': 'tool', 'tool_call_id': 't1', 'content': 'tool result'},
        {'role': 'assistant', 'content': 'done'}
    ]
    # Should not raise
    validate_tool_message_order(messages)


def test_validate_tool_message_order_invalid_sequence_missing_id():
    messages = [
        {'role': 'assistant', 'content': 'calling tool', 'tool_calls': [{}]},
    ]
    with pytest.raises(ValueError):
        validate_tool_message_order(messages)


def test_determine_response_type_tool_call_and_function_and_direct():
    m_tool = DummyMessage(tool_calls=[{'id': '1'}])
    m_func = DummyMessage(function_call={'name': 'fn'})
    m_direct = DummyMessage(content='Hello')
    assert determine_response_type(m_tool) == 'tool_call'
    assert determine_response_type(m_func) == 'function_call'
    assert determine_response_type(m_direct) == 'direct'


def test_process_direct_response_appends_and_returns_content(monkeypatch, tmp_path):
    # Prepare a dummy conversation history and log file
    from monitor import config
    config.CONVERSATION_HISTORY = []
    log_file = tmp_path / "conv.log"
    config.CONVERSATION_LOG_FILE = open(str(log_file), 'w')

    # Mock the imported functions
    def mock_normalize_message(msg):
        """Mock normalize_message to convert DummyMessage to dict"""
        if hasattr(msg, 'role'):
            result = {'role': msg.role}
        else:
            result = {'role': 'assistant'}
        
        if hasattr(msg, 'content'):
            result['content'] = msg.content
            
        return result
    
    def mock_count_message_tokens(msg):
        """Mock token counting"""
        return 10
    
    def mock_update_token_usage(*args, **kwargs):
        """Mock token usage update"""
        pass

    def _stub_append_to_history_with_count(message, history=None, *args, **kwargs):
        if history is None:
            history = config.CONVERSATION_HISTORY
        history.append(message)
    
    # Apply monkeypatches
    monkeypatch.setattr(llm_utils, 'normalize_message', mock_normalize_message)
    monkeypatch.setattr(llm_utils, 'count_message_tokens', mock_count_message_tokens)
    monkeypatch.setattr(llm_utils, 'update_token_usage', mock_update_token_usage)
    monkeypatch.setattr(llm_utils, 'append_to_history_with_count', _stub_append_to_history_with_count)

    msg = DummyMessage(content='Hello from AI')
    content = llm_utils.process_direct_response(msg)
    assert content == 'Hello from AI'
    assert len(config.CONVERSATION_HISTORY) == 1
    config.CONVERSATION_LOG_FILE.close()


def test_extract_tool_calls_and_append_fixed(monkeypatch):
    # Create a simple object that acts like a tool call with an id attribute
    class ToolCallObj:
        def __init__(self, tool_id):
            self.id = tool_id
    
    # Build a response with choices[0].message having tool_calls as objects and dicts
    obj_tool_call = ToolCallObj('b')
    msg = DummyMessage(content='do tools', tool_calls=[{'id': 'a'}, obj_tool_call])
    choice = DummyChoice(message=msg)
    resp = DummyResponse(choices=[choice])

    from monitor import config
    config.CONVERSATION_HISTORY = []

    # Mock normalize_message to include tool_calls in the normalized message
    def mock_normalize_message(msg):
        """Mock normalize_message to convert DummyMessage to dict"""
        result = {
            'role': getattr(msg, 'role', 'assistant'),
            'content': getattr(msg, 'content', None)
        }
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            result['tool_calls'] = msg.tool_calls
        return result
    
    def mock_sanitize_messages(messages):
        """Mock sanitize_messages to return input as-is"""
        return messages
    
    def mock_count_message_tokens(msg):
        """Mock token counting"""
        return 10
    
    def mock_update_token_usage(*args, **kwargs):
        """Mock token usage update"""
        pass

    def _stub_append_to_history_with_count(message, history=None, *args, **kwargs):
        if history is None:
            history = config.CONVERSATION_HISTORY
        history.append(message)
    
    # Apply all monkeypatches
    monkeypatch.setattr(llm_utils, 'normalize_message', mock_normalize_message)
    monkeypatch.setattr(llm_utils, 'sanitize_messages', mock_sanitize_messages)
    monkeypatch.setattr(llm_utils, 'count_message_tokens', mock_count_message_tokens)
    monkeypatch.setattr(llm_utils, 'update_token_usage', mock_update_token_usage)
    monkeypatch.setattr(llm_utils, 'append_to_history_with_count', _stub_append_to_history_with_count)

    # Debug: check the input objects before calling extract_tool_calls
    print(f"DEBUG: msg.tool_calls = {msg.tool_calls}")
    print(f"DEBUG: Type of tool_calls[0]: {type(msg.tool_calls[0])}")
    print(f"DEBUG: Type of tool_calls[1]: {type(msg.tool_calls[1])}")
    print(f"DEBUG: tool_calls[1].__dict__ = {getattr(msg.tool_calls[1], '__dict__', 'NO __dict__')}")
    print(f"DEBUG: tool_calls[1].id = {getattr(msg.tool_calls[1], 'id', 'NO id attr')}")

    tool_calls = llm_utils.extract_tool_calls(resp)
    
    # Debug: check what we got back
    print(f"DEBUG: extract_tool_calls returned: {tool_calls}")
    
    # Should return list of dicts with ids
    # The extract_tool_calls function should convert both the dict and the object to dicts
    assert len(tool_calls) == 2, f"Expected 2 tool calls, got {len(tool_calls)}: {tool_calls}"
    assert any(tc.get('id') == 'a' for tc in tool_calls), f"Expected tool call with id 'a', got: {tool_calls}"
    assert any(tc.get('id') == 'b' for tc in tool_calls), f"Expected tool call with id 'b', got: {tool_calls}"
    assert len(config.CONVERSATION_HISTORY) == 1


def test_process_response_by_finish_reason_variants(tmp_path):
    # refusal
    msg = DummyMessage(content='refusal')
    choice = DummyChoice(message=msg, finish_reason='refusal')
    resp = DummyResponse(choices=[choice])
    from monitor import config
    config.CONVERSATION_HISTORY = [{'role': 'user', 'content': 'bad'}]
    res = llm_utils.process_response_by_finish_reason(resp)
    assert 'refused' in res

    # length
    choice2 = DummyChoice(message=msg, finish_reason='length')
    resp2 = DummyResponse(choices=[choice2])
    assert 'Length too long' in llm_utils.process_response_by_finish_reason(resp2)

    # stop with content
    msg3 = DummyMessage(content='OK')
    choice3 = DummyChoice(message=msg3, finish_reason='stop')
    resp3 = DummyResponse(choices=[choice3])
    from monitor import config as cfg
    cfg.CONVERSATION_LOG_FILE = open(str(tmp_path / 'tmp_llm_log'), 'w')
    result = llm_utils.process_response_by_finish_reason(resp3)
    assert result == 'OK' or result == 'Ok.'
    cfg.CONVERSATION_LOG_FILE.close()


def test_call_litellm_completion_sets_reasoning_kwargs(monkeypatch):
    # Patch litellm.completion to capture kwargs
    captured = {}
    def fake_completion(**kwargs):
        captured.update(kwargs)
        return {'choices': []}
    
    def mock_function_descriptions(*args):
        return []
    
    monkeypatch.setattr(llm_utils.litellm, 'completion', fake_completion)
    monkeypatch.setattr(llm_utils, 'function_descriptions', mock_function_descriptions)
    
    # Ensure config.REASONING_MODEL_PREFIX triggers
    from monitor import config
    config.REASONING_MODEL_PREFIX = 'openai/o3'
    config.REASONING_EFFORT = 2
    config.REASONING_MAX_COMPLETION_TOKENS = 50
    model = 'openai/o3-test'
    messages = [{'role': 'user', 'content': 'hi'}]
    res = llm_utils.call_litellm_completion(model, messages)
    assert 'reasoning_effort' in captured and captured['reasoning_effort'] == 2
    assert 'max_completion_tokens' in captured and captured['max_completion_tokens'] == 50
