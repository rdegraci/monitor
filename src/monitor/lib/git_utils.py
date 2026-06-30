import logging
import subprocess
from typing import List, Optional, Tuple

from colored import fg, attr
from monitor.lib.pygments_stubs import TerminalFormatter, highlight

logger = logging.getLogger(__name__)

# Common colors
yellow = fg('yellow')
reset = attr('reset')


def ensure_non_empty_string(value: str, name: str) -> str:
    """Validate that a value is a non-empty string, else raise ValueError.

    Args:
        value: The value to validate.
        name: A human-friendly name for error messages.
    Returns:
        The validated string (stripped).
    Raises:
        ValueError: If the value is not a non-empty string.
    """
    if not isinstance(value, str) or not value.strip():
        logger.error("Invalid %s provided: must be a non-empty string", name)
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def run_git_capture(cmd_args: List[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Run a git command and capture stdout/stderr.

    Returns (stdout, stderr, error_message). If error_message is not None, the call failed.
    """
    try:
        logger.debug("Executing git command: %s", ' '.join(cmd_args))
        result = subprocess.run(cmd_args, check=True, text=True, capture_output=True)
        logger.info("Git command succeeded: %s", ' '.join(cmd_args))
        return result.stdout, result.stderr, None
    except subprocess.CalledProcessError as e:
        logger.debug("Git command failed: %s; error: %s", ' '.join(cmd_args), e, exc_info=True)
        return None, None, f"An error occurred while executing {' '.join(cmd_args)}: {e}"


def highlight_text(text: str, lexer) -> str:
    """Return syntax-highlighted text for terminal display using the given lexer."""
    return highlight(text, lexer, TerminalFormatter(reset=True))


def print_highlight_or_empty(text: str, lexer, empty_message: str) -> None:
    """Print highlighted text if non-empty; else print a yellow empty message.

    This function produces side effects (prints) and returns None.
    """
    if text:
        print(highlight_text(text, lexer))
    else:
        print(f"{yellow}{empty_message}{reset}")
