import logging
import os

from monitor._stubs import TavilyClient
from monitor.lib.display_output import print_colored_info
from monitor.lib.optional_deps import OptionalDependencyError, missing_extra_message, require_extra

logger = logging.getLogger(__name__)


def configureTavily():
    """Create and return a TavilyClient.

    Warns if the TAVILY_API_KEY environment variable is missing, but still
    constructs the client when the ``network`` extra is installed.

    Returns:
        TavilyClient: Configured Tavily client instance.
    """
    if TavilyClient is None:
        require_extra("network", feature="web search")
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        logger.warning("TAVILY_API_KEY environment variable is not set.")
    return TavilyClient(api_key=api_key)


def tavily_search(query, print_func=print_colored_info):
    """Perform a Tavily Q&A search for the given query.

    Args:
        query (str): The search query.
        print_func (Callable[[str], None], optional): Function used to print informational output.
            Defaults to print_colored_info.

    Returns:
        dict | Any | str: If the Tavily client returns a dictionary, the dictionary is returned as-is.
        Otherwise, the raw response object is returned (and printed via print_func). On failure,
        an error message string is returned.
    """
    try:
        tavily = configureTavily()
    except OptionalDependencyError as exc:
        return str(exc)
    logger.debug("Starting tavily search with query: %s", query)
    logger.info("Tavily search for %s", query)
    print_func(f"Searching for: {query}")
    try:
        response = tavily.search(query=query, search_depth="advanced")

        # Log successful completion with metrics
        if isinstance(response, dict):
            results = response.get("results")
            if isinstance(results, list):
                logger.info(
                    "Search completed successfully; results count: %d", len(results)
                )
            else:
                logger.info("Search completed successfully with dictionary response")
            return response
        else:
            logger.info("Search completed successfully with non-dictionary response")
            print_func(response)
            return response
    except Exception as e:
        error_message = f"Error performing search: {str(e)}"
        logger.error(
            "Failed to perform Tavily search for query: %s. Error: %s",
            query,
            str(e),
            exc_info=True,
        )
        if TavilyClient is None:
            return missing_extra_message("network", feature="web search")
        return error_message
