
import os
import logging
from tavily import TavilyClient
from colored import fg, attr

from pygments import highlight
from pygments.lexers import BashLexer, MarkdownLexer, DiffLexer
from pygments.formatters import TerminalFormatter

blue = fg('blue')
red = fg('red')
yellow = fg('yellow')
reset = attr('reset')

logger = logging.getLogger(__name__)

def tavily_search(query):
    TAVILY = TavilyClient(api_key=os.getenv('TAVILY_API_KEY'))

    logger.debug("Starting tavily search with query: %s", query)
    logger.info("Tavily search for %s", query)
    print(f"{yellow}Searching for: {query}{reset}")
    try:
        response = TAVILY.qna_search(query=query, search_depth="advanced")
        
        # Log successful completion with metrics
        if isinstance(response, dict):
            result_length = len(response.get('answer', '')) if 'answer' in response else 0
            logger.info("Search completed successfully. Answer length: %d characters", result_length)
        else:
            logger.info("Search completed successfully with non-dictionary response")
            
        return response
    except Exception as e:
        error_message = f"Error performing search: {str(e)}"
        logger.error("Failed to perform Tavily search for query: %s. Error: %s", query, str(e), exc_info=True)
        return error_message
