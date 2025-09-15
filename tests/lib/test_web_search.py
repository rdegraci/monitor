import pytest
from unittest.mock import patch, MagicMock
from monitor.lib import web_search

@patch('monitor.lib.web_search.TavilyClient')
def test_tavily_search_success(mock_client):
    # Simulate a good response
    mock_client.return_value.qna_search.return_value = {'answer': 'The Eiffel Tower is in Paris.'}
    result = web_search.tavily_search('Where is the Eiffel Tower?')
    assert isinstance(result, dict)
    assert result['answer'] == 'The Eiffel Tower is in Paris.'
    mock_client.return_value.qna_search.assert_called_once_with(query='Where is the Eiffel Tower?', search_depth='advanced')

@patch('monitor.lib.web_search.TavilyClient')
def test_tavily_search_non_dict_response(mock_client):
    # Simulate response not being a dict
    mock_client.return_value.qna_search.return_value = 'Some string answer!'
    result = web_search.tavily_search('Some question?')
    assert result == 'Some string answer!'

@patch('monitor.lib.web_search.TavilyClient')
def test_tavily_search_exception(mock_client):
    # Simulate exception in qna_search
    mock_client.return_value.qna_search.side_effect = Exception('API Error!')
    result = web_search.tavily_search('Error please')
    assert 'Error performing search' in result
    assert 'API Error' in result
