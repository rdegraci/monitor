"""`:agent logfile <name|index>` — print the absolute logfile path for a session.

Output is just the path (no decoration) so it can be piped: ``tail -f $(:agent logfile mysession)``.
"""

import logging

from monitor.lib import subagent_logging
from monitor.lib.terminal_commands_util import user_feedback

logger = logging.getLogger(__name__)


def agent_logfile(tokens):
    """Print the logfile path for a session, resolved via
    subagent_logging.find_logfile_for_session_name."""
    from monitor.lib.terminal_commands import _resolve_index_to_session_name

    if len(tokens) < 2:
        user_feedback("Usage: logfile <session_name>")
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
        logfile_path = subagent_logging.find_logfile_for_session_name(target_session)
        if logfile_path:
            # Machine-friendly: print only the path, no prefix.
            print(logfile_path)
            return
        user_feedback(f"No logfile found for session '{target_session}'.")
        return
    except Exception as e:
        logger.error(f"Error finding logfile for session '{target_session}': {e}", exc_info=True)
        user_feedback(f"Failed to get logfile for session '{target_session}'. See logs for details.")
        return
