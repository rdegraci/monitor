"""`:agent send <name|index> [--] <text>` — pipe text into a running session."""

import logging

from monitor.lib.terminal_commands_util import user_feedback

logger = logging.getLogger(__name__)


def agent_send(tokens):
    """Send text to a running screen session via _SCREEN_HANDLER.send_to_session.

    The ``--`` separator is honored so users can send commands that
    would otherwise be parsed as flags. Without ``--`` everything after
    the session name is joined with spaces.
    """
    from monitor.lib.terminal_commands import _SCREEN_HANDLER, _resolve_index_to_session_name

    if len(tokens) < 3:
        user_feedback("Usage: send <session_name> [--] <text>")
        return
    target_session = tokens[1]
    if str(target_session).isdigit():
        try:
            target_session = _resolve_index_to_session_name(target_session)
        except Exception as e:
            logger.error(f"Error resolving session index '{tokens[1]}': {e}", exc_info=True)
            user_feedback(f"Failed to resolve session index '{tokens[1]}'. See logs for details.")
            return

    # Extract text after '--' if present; otherwise everything after the session name.
    if '--' in tokens:
        sep_index = tokens.index('--')
        text_parts = tokens[sep_index + 1:]
    else:
        text_parts = tokens[2:]
    if not text_parts:
        user_feedback("Usage: send <session_name> [--] <text>")
        return
    text_to_send = ' '.join(text_parts)
    try:
        result = _SCREEN_HANDLER.send_to_session(target_session, text_to_send)
        if result:
            user_feedback(f"Sent text to session '{target_session}'.")
            logger.info(f"Sent to session '{target_session}': {text_to_send}")
        else:
            user_feedback(f"Failed to send text to session '{target_session}'. See logs for details.")
            logger.error(f"send_to_session returned falsy for session '{target_session}'.")
        return
    except Exception as e:
        logger.error(f"Error sending text to session '{target_session}': {e}", exc_info=True)
        user_feedback(f"Failed to send text to session '{target_session}'. See logs for details.")
        return
