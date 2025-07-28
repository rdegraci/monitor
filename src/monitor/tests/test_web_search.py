import pytest
from unittest.mock import patch, MagicMock
from monitor.lib import web_search

@patch('lib.web_search.TAVILY')
def test_tavily_search_success(mock_tavily):
    # Simulate a good response
    mock_tavily.qna_search.return_value = {'answer': 'The Eiffel Tower is in Paris.'}
    result = web_search.tavily_search('Where is the Eiffel Tower?')
    assert isinstance(result, dict)
    assert result['answer'] == 'The Eiffel Tower is in Paris.'
    mock_tavily.qna_search.assert_called_once_with(query='Where is the Eiffel Tower?', search_depth='advanced')

@patch('lib.web_search.TAVILY')
def test_tavily_search_non_dict_response(mock_tavily):
    # Simulate response not being a dict
    mock_tavily.qna_search.return_value = 'Some string answer!'
    result = web_search.tavily_search('Some question?')
    assert result == 'Some string answer!'

@patch('lib.web_search.TAVILY')
def test_tavily_search_exception(mock_tavily):
    # Simulate exception in qna_search
    mock_tavily.qna_search.side_effect = Exception('API Error!')
    result = web_search.tavily_search('Error please')
    assert 'Error performing search' in result
    assert 'API Error' in result
