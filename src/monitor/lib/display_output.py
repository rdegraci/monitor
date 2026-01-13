# NOTE: No direct or legacy token counting or usage estimation logic exists in this file. 
# If token logic is required in the future, use count_message_tokens and update_token_usage from monitor.lib/token_management.py. 

import os
import logging
import sys
from datetime import datetime

from pygments import highlight
from pygments.lexers import MarkdownLexer
from pygments.formatters import TerminalFormatter

from monitor import config

logger = logging.getLogger(__name__)
from monitor.lib.colors import red, yellow, blue, reset

def print_colored_error(message):
    print(f"{red}{message}{reset}", file=sys.stderr)

def print_colored_info(message):
    print(f"{yellow}{message}{reset}", file=sys.stderr)

def display_query_result(output_string, update_history_count=None):
    """Highlight and display the result of a query.

    Args:
        output_string (str): The string to display.
        update_history_count (callable, optional): If provided, will be called to update history count.
    """
    logger.debug("Displaying query result for input...")
    if output_string is not None and not isinstance(output_string, str):
        logger.warning(f"display_query_result received non-string output: {type(output_string).__name__}")
    highlightMarkdown(output_string)
    if update_history_count is not None:
        update_history_count()

def highlightMarkdown(query_result):
    if query_result is None:
        print(f"\n{red}No query result.{reset}")
        return
    if not isinstance(query_result, str):
        try:
            logger.debug(f"highlightMarkdown received non-string output: {type(query_result).__name__}")
        except Exception:
            pass
        return
    highlighted_output = highlight(query_result, MarkdownLexer(), TerminalFormatter(reset=True))
    print(f"\n{yellow}STX{reset}")
    print(f"{highlighted_output}{yellow}ETX{reset}\n")
    print("*******************")
    print("*******************")
    print("*******************")
    print("Generated:", datetime.now().strftime("%Y-%m-%d %H:%M:%S\n"))

def format_prompt_display(conversation_count, tokens_remaining, cwd=None, model=None, extra_history_str="", context_remaining=None, rate_remaining=None, total_used=None):
    """Format the prompt display for the CLI.

    Args:
        conversation_count (int): Current conversation history count.
        tokens_remaining (int): Number of tokens remaining in allocation (backward compatible).
        cwd (str, optional): Current working directory; if None, will attempt to use os.getcwd().
        model (str, optional): The model name to display.
        extra_history_str (str): Extra string to include about history (optional).
        context_remaining (int, optional): Context remaining; if None, derived from tokens_remaining.
        rate_remaining (int, optional): Rate limiter remaining; if None, derived from monitor.lib.rate_limiter.RATE_LIMITER when available.
        total_used (int, optional): Total usage; if None, uses config.TOTAL_TOKEN_COUNT when available.

    Returns:
        str: The formatted prompt display string.
    """
    try:
        tch_count = f"{yellow}{conversation_count}{reset}"
    except Exception as e:
        tch_count = "Error in calculating conversation history count"
        logger.error(f"Error: {e}", exc_info=True)

    c_count = ""
    r_count = ""
    u_count = ""

    try:
        if context_remaining is None:
            context_remaining = tokens_remaining

        if context_remaining is not None:
            if context_remaining < 0:
                try:
                    logger.warning(f"Negative context_remaining detected in prompt: {context_remaining}. Total tokens: {config.TOTAL_TOKEN_COUNT}, Max allowed: {config.MAX_TOKEN_COUNT}")
                    # Print a snippet of recent conversation history if available
                    if hasattr(config, 'CONVERSATION_HISTORY') and len(config.CONVERSATION_HISTORY) >= 2:
                        logger.warning(f"Recent conversation history (last 2): {config.CONVERSATION_HISTORY[-2:]}")
                except Exception as log_err:
                    print(f"Error logging negative context_remaining: {log_err}")
            context_color = red if context_remaining == 0 else blue
            c_count = f"{context_color}{context_remaining}{reset}"
    except Exception as e:
        c_count = "Error in calculating context count"
        logger.error(f"Error: {e}", exc_info=True)

    try:
        if rate_remaining is None:
            try:
                from monitor.lib.rate_limiter import RATE_LIMITER
                try:
                    limit = getattr(RATE_LIMITER, 'limit', None)
                    current = getattr(RATE_LIMITER, 'current_usage', None)
                    if limit is not None and current is not None:
                        rate_remaining = limit - current
                except Exception:
                    pass
            except Exception:
                pass

        if rate_remaining is not None:
            rate_color = red if rate_remaining == 0 else blue
            r_count = f"{rate_color}{rate_remaining}{reset}"
    except Exception as e:
        r_count = "Error in calculating rate limiter remaining"
        logger.error(f"Error: {e}", exc_info=True)

    try:
        if total_used is None:
            try:
                total_used = getattr(config, 'TOTAL_TOKEN_COUNT', None)
            except Exception:
                total_used = None

        if total_used is not None:
            used_color = red if total_used == 0 else blue
            u_count = f"{used_color}{total_used}{reset}"
    except Exception as e:
        u_count = "Error in calculating total usage"
        logger.error(f"Error: {e}", exc_info=True)

    if cwd is None:
        try:
            cwd = os.getcwd()
        except Exception as e:
            cwd = "Error in getting current working directory"
            logger.error(f"Error: {e}", exc_info=True)

    model_str = f"{model}" if model is not None else ""

    prefix = getattr(config, 'REASONING_MODEL_PREFIX', '')
    effort = getattr(config, 'REASONING_EFFORT', '')
    reasoning_str = effort if isinstance(model, str) and prefix and (prefix in model) else ""

    parts = []
    if c_count:
        parts.append(f"C:{c_count}")
    if r_count:
        parts.append(f"R:{r_count}")
    if u_count:
        parts.append(f"U:{u_count}")
    parts.append(f"H:{tch_count}{extra_history_str}")

    stats_str = " ".join(parts)

    return f"\n{cwd}\n{stats_str}\n{model_str} {reasoning_str} ] "
