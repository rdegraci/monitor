import pytest
import logging
from unittest.mock import patch, MagicMock
from monitor.lib import summarizers

@pytest.fixture(autouse=True)
def set_debug_logging():
    logging.getLogger('lib.summarizers').setLevel(logging.DEBUG)

@patch('lib.summarizers.litellm.completion')
def test_summarize_conversation_for_platform_twitch(mock_completion):
    # Prepare the fake litellm response
    mock_summary_text = 'Summary: This is a test summary.'
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message={"content": mock_summary_text})]
    mock_completion.return_value = mock_response

    fake_history = [
        {'role': 'user', 'content': 'A User started the session.'},
    ] * 10  # Simulate a long enough history

    model = 'fake-model'

    summary = summarizers.summarize_conversation_for_twitch(fake_history, model)
    assert summary == mock_summary_text
    assert mock_completion.called
    call_args = mock_completion.call_args[1]  # Get kwargs
    assert call_args['model'] == model
    assert 'twitch' in call_args['messages'][1]['content'] or 'Twitch' in call_args['messages'][1]['content']

@patch('lib.summarizers.litellm.completion')
def test_history_too_short(mock_completion):
    # Short history (<10)
    fake_history = [{'role': 'user', 'content': 'Hello'}]
    model = 'model'
    result = summarizers.summarize_conversation_for_twitter(fake_history, model)
    assert result is None
    mock_completion.assert_not_called()

@patch('lib.summarizers.litellm.completion')
def test_unknown_platform_returns_empty(mock_completion):
    fake_history = [
        {'role': 'user', 'content': 'Something'},
    ] * 11
    model = 'model'
    result = summarizers.summarize_conversation_for_platform('myspace', model, fake_history)
    assert result == ''
    mock_completion.assert_not_called()
