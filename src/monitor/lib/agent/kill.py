"""`:agent kill <name|index>` — kill a screen session and clean up its orchestrator poller."""

import logging

from monitor.lib.terminal_commands_util import user_feedback, remove_orchestrator_entries_by_target

logger = logging.getLogger(__name__)


def agent_kill(tokens):
    """Kill a session via _SCREEN_HANDLER.kill_session, then ask the
    orchestrator registry to remove and stop any pollers tied to the
    same session key.

    The orchestrator cleanup trusts the documented return shape of
    ``remove_orchestrator_entries_by_target`` (``Dict[str, List[entry_dict]]``)
    and lets the helper do the stop()/join() work internally — see the
    historical note in terminal_commands_util.py for why the prior
    140-line defensive maze was removed.
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

        # Orchestrator cleanup — helper handles stop()+join() internally.
        try:
            removed = remove_orchestrator_entries_by_target(target_session)
            removed_entries = removed.get(target_session, []) if isinstance(removed, dict) else []
            if removed_entries:
                logger.info(
                    "Stopped %d orchestrator poller(s) for session '%s'.",
                    len(removed_entries), target_session,
                )
                user_feedback(f"Stopped orchestrator poller for session '{target_session}'.")
            else:
                logger.info(
                    "No orchestrator poller entries found for session '%s'.",
                    target_session,
                )
        except Exception as e:
            logger.error(
                "Exception while cleaning up orchestrator poller for session '%s': %s",
                target_session, e, exc_info=True,
            )
        return
    except Exception as e:
        logger.error(f"Error killing screen session '{target_session}': {e}", exc_info=True)
        user_feedback(f"Failed to kill screen session '{target_session}'. See logs for details.")
        return
