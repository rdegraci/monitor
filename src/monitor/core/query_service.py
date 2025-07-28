"""
Query service module to resolve circular dependencies.

This module acts as a broker for the query functionality between 
conversation.py and command_processing.py, eliminating direct
circular imports between these modules.
"""

import logging

logger = logging.getLogger(__name__)

# Global registry for the query function
_query_function = None

def register_query_function(func):
    """Register the query function from conversation module.
    
    Args:
        func: The query function to register
    """
    global _query_function
    logger.debug("Registering query function")
    _query_function = func

def query(*args, **kwargs):
    """Execute the registered query function.
    
    This acts as a proxy to the actual query function in conversation.py.
    
    Args:
        *args: Positional arguments to pass to the query function
        **kwargs: Keyword arguments to pass to the query function
    
    Returns:
        The result of the query function
        
    Raises:
        RuntimeError: If the query function has not been registered yet
    """
    global _query_function
    if _query_function is not None:
        return _query_function(*args, **kwargs)
    else:
        logger.error("Query function accessed before registration")
        raise RuntimeError("Query function not initialized. Ensure application initialization is complete.")