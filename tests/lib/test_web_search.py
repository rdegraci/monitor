import json
import pytest
from unittest.mock import patch, MagicMock
from monitor.lib import web_search


@patch("monitor.lib.web_search.TavilyClient")
def test_tavily_search_success(mock_client):
    """Test successful Tavily search returning dict with 'query' and 'results'."""
    # Simulate a good response matching the example structure
    example_response = {
        "query": "Where is the Eiffel Tower?",
        "results": [
            {
                "title": "Eiffel Tower - Wikipedia",
                "url": "https://en.wikipedia.org/wiki/Eiffel_Tower",
                "content": "The Eiffel Tower is a wrought-iron lattice tower on the Champ de Mars in Paris, France.",
            }
        ],
    }
    mock_client.return_value.search.return_value = example_response
    result = web_search.tavily_search("Where is the Eiffel Tower?")
    assert isinstance(result, dict)
    assert result.get("query") == "Where is the Eiffel Tower?"
    assert isinstance(result.get("results"), list)
    assert result["results"][0]["title"] == "Eiffel Tower - Wikipedia"
    mock_client.return_value.search.assert_called_once_with(
        query="Where is the Eiffel Tower?", search_depth="advanced"
    )


@patch("monitor.lib.web_search.TavilyClient")
def test_tavily_search_non_dict_response(mock_client):
    """Test non-dict response is passed through unchanged."""
    # Simulate response not being a dict
    mock_client.return_value.search.return_value = "Some string answer!"
    result = web_search.tavily_search("Some question?")
    assert result == "Some string answer!"


@patch("monitor.lib.web_search.TavilyClient")
def test_tavily_search_exception(mock_client):
    """Test exception handling returns error message string."""
    # Simulate exception in search
    mock_client.return_value.search.side_effect = Exception("API Error!")
    result = web_search.tavily_search("Error please")
    assert "Error performing search" in result
    assert "API Error" in result
