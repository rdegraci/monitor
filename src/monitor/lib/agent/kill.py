"""`:agent kill <name|index>` — kill a screen session."""

import logging

from monitor.lib.terminal_commands_util import user_feedback

logger = logging.getLogger(__name__)


def agent_kill(tokens):
    """Kill a session via _SCREEN_HANDLER.kill_session.

    Killing the screen session terminates the sub-agent process; its socket to
    the orchestrator listener then closes, which the listener records as a
    (dirty) disconnect — so no explicit orchestrator-side cleanup is needed
    here. (The legacy poller registry this used to clean up was removed with
    the inverted status-socket model.)
    """
    from monitor.lib.terminal_commands import _SCREEN_HANDLER, _resolve_index_to_session_name

    if len(tokens) < 2:
        user_feedback("Usage: kill <session_name>")
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
        result = _SCREEN_HANDLER.kill_session(target_session)
        if not result:
            user_feedback(f"Failed to kill screen session '{target_session}'. See logs for details.")
            logger.error(f"kill_session returned falsy for session '{target_session}'.")
            return
        user_feedback(f"Successfully killed screen session '{target_session}'.")
        logger.info(f"Killed screen session '{target_session}'.")
        return
    except Exception as e:
        logger.error(f"Error killing screen session '{target_session}': {e}", exc_info=True)
        user_feedback(f"Failed to kill screen session '{target_session}'. See logs for details.")
        return
