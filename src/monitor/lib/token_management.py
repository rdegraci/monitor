
"""
Token management module – THE SINGLE CANONICAL API for token counting and usage tracing.
This module is the sole, official, and *mandatory* entry point for any token counting,
measurement, or update logic across the codebase.

-------------------------------------------------------------------------------------------
!! WARNING !!
NEVER use `estimate_token_count` directly, nor import it (or similar helpers)
from `lib/rate_limiter.py` or elsewhere. All token counting and updating
MUST go through the helpers provided here in this module, and nowhere else.

DO NOT invoke or wrap low-level token or usage helpers outside this module.
Any attempt to count or update tokens from non-canonical sources is considered
a violation of code maintainership, traceability, and proper auditing.

All other code (such as `history.py`, `conversation.py`, and all future code)
MUST always import token counters and update helpers exclusively from this module.
Changes to token policy, runtime auditing, or reporting should only be made here.

-------------------------------------------------------------------------------------------

This module resolves circular imports (notably between history.py and conversation.py)
and ensures all token handling is safely centralized, traceable, and auditable.
"""

import logging
import sys
from monitor import config
from monitor.lib.rate_limiter import estimate_token_count

logger = logging.getLogger(__name__)
from monitor.lib.colors import red, reset

def count_message_tokens(message):
    """
    Canonical function to count tokens in a message.
    Use THIS function for all message token counting
    across the codebase—never call `estimate_token_count` directly!
    
    Args:
        message (dict): Message dictionary with 'content' key
        
    Returns:
        int: Estimated token count
        
    Raises:
        Exception: If token counting fails
    """
    try:
        content = message.get('content', '')
        return estimate_token_count(content)
    except Exception as e:
        logger.error(f"Error counting message tokens: {str(e)}", exc_info=True)
        raise

def update_token_usage(tokens_or_response):
    """
    Canonical function to update the total token count in config.TOTAL_TOKEN_COUNT.
    This is THE ONLY approved location for token count increment logic.

    Accepts either an int token count or a model response object with usage info.

    Args:
        tokens_or_response (int or object):
          int for token count, or object with `usage.total_tokens` attribute

    Returns:
        int: Updated total token count
    """
    try:
        from monitor import config  # For safe circular import resolution

        # Check for TOTAL_TOKEN_COUNT as None or missing at absolute top
        if not hasattr(config, "TOTAL_TOKEN_COUNT") or getattr(config, "TOTAL_TOKEN_COUNT") is None:
            logger.warning("TOTAL_TOKEN_COUNT is missing or None at entry; initializing to 0.")
            config.TOTAL_TOKEN_COUNT = 0

        # Robust handling: Treat None argument as 0 tokens, log warning
        tokens = None
        if tokens_or_response is None:
            logger.warning("Token usage input is None; treating as 0 tokens.")
            tokens = 0
        elif hasattr(tokens_or_response, 'usage') and hasattr(tokens_or_response.usage, 'total_tokens'):
            total_tokens = tokens_or_response.usage.total_tokens
            if total_tokens is None:
                logger.warning("Token usage in response is None; treating as 0 tokens.")
                tokens = 0
            else:
                tokens = total_tokens
        elif isinstance(tokens_or_response, (int, float)):
            tokens = int(tokens_or_response)
        else:
            # If it's not an int/float and doesn't have usage info, skip the update
            logger.warning(f"Invalid token input type: {type(tokens_or_response)}, skipping update")
            try:
                return config.TOTAL_TOKEN_COUNT if getattr(config, "TOTAL_TOKEN_COUNT", None) is not None else 0
            except Exception:
                logger.error("Failed to access TOTAL_TOKEN_COUNT after invalid input", exc_info=True)
                return 0

        # Store current count for error recovery
        try:
            current_count = config.TOTAL_TOKEN_COUNT
        except Exception:
            logger.error("Failed to read current TOTAL_TOKEN_COUNT", exc_info=True)
            current_count = 0

        # Ensure tokens is not None before performing addition
        tokens_to_add = 0 if tokens is None else tokens

        # Update the count
        try:
            config.TOTAL_TOKEN_COUNT += tokens_to_add
            return config.TOTAL_TOKEN_COUNT
        except Exception:
            logger.error("Failed to update TOTAL_TOKEN_COUNT", exc_info=True)
            # Try to return the previous count
            try:
                return current_count
            except Exception:
                logger.error("Failed to return previous count", exc_info=True)
                return 0

    except Exception as e:
        logger.error(f"Error updating token usage: {str(e)}")
        # Final fallback
        try:
            from monitor import config
            return config.TOTAL_TOKEN_COUNT if getattr(config, "TOTAL_TOKEN_COUNT", None) is not None else 0
        except Exception:
            logger.error("Complete failure accessing config, returning 0", exc_info=True)
            return 0


