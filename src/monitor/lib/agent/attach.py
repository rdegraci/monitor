"""`:agent attach <name|index>` — re-attach to an existing screen session in the current TTY."""

import logging
import subprocess

from monitor.lib.screen_handler_utils import resolve_screen_token
from monitor.lib.terminal_commands_util import user_feedback

logger = logging.getLogger(__name__)


def agent_attach(tokens):
    """Attach to an existing screen session using ``screen -r <token>``.

    The user-facing token (session name or numeric index) is first
    resolved to the actual screen token (e.g. ``37082.mysession``) via
    ``resolve_screen_token``. If resolution fails, falls back to using
    the raw token verbatim — screen will give its own error if that
    doesn't match either.
    """
    from monitor.lib.terminal_commands import _SCREEN_HANDLER, _resolve_index_to_session_name

    if len(tokens) < 2:
        user_feedback("Usage: attach <session_name>")
        return
    target_session = tokens[1]
    if str(target_session).isdigit():
        try:
            target_session = _resolve_index_to_session_name(target_session)
        except Exception as e:
            logger.error(f"Error resolving session index '{tokens[1]}': {e}", exc_info=True)
            user_feedback(f"Failed to resolve session index '{tokens[1]}'. See logs for details.")
            return
    try:
        try:
            resolved_token = resolve_screen_token(_SCREEN_HANDLER.screen_cmd, target_session)
        except Exception as e:
            logger.error(f"Error resolving screen token for '{target_session}': {e}", exc_info=True)
            resolved_token = None

        token_to_use = resolved_token if resolved_token else target_session
        logger.info(f"Attaching to screen session token: '{token_to_use}'")

        # No capture_output — let screen attach to the current TTY.
        result = subprocess.run(['screen', '-r', token_to_use])
        if result.returncode != 0:
            logger.error(f"Failed to attach to screen session '{token_to_use}': returncode {result.returncode}")
            user_feedback(f"Failed to attach to screen session '{target_session}'. See logs for details.")
        else:
            logger.info(f"Attached to screen session '{token_to_use}'.")
        return
    except Exception as e:
        logger.error(f"Exception while trying to attach to screen session '{target_session}': {e}", exc_info=True)
        user_feedback(f"An error occurred while attaching to session '{target_session}'. See logs for details.")
        return
