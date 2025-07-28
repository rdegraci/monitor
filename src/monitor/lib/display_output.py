
# NOTE: No direct or legacy token counting or usage estimation logic exists in this file. 
# If token logic is required in the future, use count_message_tokens and update_token_usage from monitor.lib/token_management.py. 

import os
import logging
import sys

from pygments import highlight
from pygments.lexers import MarkdownLexer
from pygments.formatters import TerminalFormatter

from monitor import config

logger = logging.getLogger(__name__)
from monitor.lib.colors import red, yellow, blue, reset

def print_colored_error(message):
    print(f"{red}{message}{reset}", file=sys.stderr)

def display_query_result(output_string, update_history_count=None):
    """Highlight and display the result of a query.

    Args:
        output_string (str): The string to display.
        update_history_count (callable, optional): If provided, will be called to update history count.
    """
    logger.debug("Displaying query result for input...")
    highlightMarkdown(output_string)
    if update_history_count is not None:
        update_history_count()

def highlightMarkdown(query_result):
    if query_result is None:
        print(f"\n{red}No query result.{reset}")
        return
    highlighted_output = highlight(query_result, MarkdownLexer(), TerminalFormatter(reset=True))
    print(f"\n{yellow}STX{reset}")
    print(f"{highlighted_output}{yellow}ETX{reset}\n")
    print("*******************")
    print("*******************")
    print("*******************\n")


def format_prompt_display(conversation_count, tokens_remaining, cwd=None, model=None, extra_history_str=""):
    """Format the prompt display for the CLI.

    Args:
        conversation_count (int): Current conversation history count.
        tokens_remaining (int): Number of tokens remaining in allocation.
        cwd (str, optional): Current working directory; if None, will attempt to use os.getcwd().
        model (str, optional): The model name to display.
        extra_history_str (str): Extra string to include about history (optional).

    Returns:
        str: The formatted prompt display string.
    """
    try:
        tch_count = f"{yellow}{conversation_count}{reset}"
    except Exception as e:
        tch_count = "Error in calculating conversation history count"
        logger.error(f"Error: {e}", exc_info=True)

    try:
        if tokens_remaining < 0:
            try:
                logger.warning(f"Negative tokens_remaining detected in prompt: {tokens_remaining}. Total tokens: {config.TOTAL_TOKEN_COUNT}, Max allowed: {config.MAX_TOKEN_COUNT}")
                # Print a snippet of recent conversation history if available
                if hasattr(config, 'CONVERSATION_HISTORY') and len(config.CONVERSATION_HISTORY) >= 2:
                    logger.warning(f"Recent conversation history (last 2): {config.CONVERSATION_HISTORY[-2:]}")
            except Exception as log_err:
                print(f"Error logging negative tokens_remaining: {log_err}")
        token_color = red if tokens_remaining == 0 else blue
        tt_count = f"{token_color}{tokens_remaining}{reset}"
    except Exception as e:
        tt_count = "Error in calculating token count"
        logger.error(f"Error: {e}", exc_info=True)

    if cwd is None:
        try:
            cwd = os.getcwd()
        except Exception as e:
            cwd = "Error in getting current working directory"
            logger.error(f"Error: {e}", exc_info=True)

    model_str = f"{model}" if model is not None else ""
    return f"\n{cwd}\nT:{tt_count} H:{tch_count}{extra_history_str} {model_str} ] "



