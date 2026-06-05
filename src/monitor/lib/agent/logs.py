"""`:agent logs <name|index>` — tail recent log output for a session."""

import logging

from monitor.lib.terminal_commands_util import user_feedback

logger = logging.getLogger(__name__)


def agent_logs(tokens):
    """Print recent log output for a session.

    Resolves numeric index tokens via the shared session-index resolver,
    then calls ``_SCREEN_HANDLER.tail_log``. The handler may return a
    list, tuple, generator, or single string — print each shape sensibly
    (strings whole, iterables line-by-line).
    """
    # Late import to avoid module-load circular dependency: terminal_commands
    # imports the dispatcher (which imports this module) only at call time.
    from monitor.lib.terminal_commands import _SCREEN_HANDLER, _resolve_index_to_session_name

    if len(tokens) < 2:
        user_feedback("Usage: logs <session_name>")
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
        log_output = _SCREEN_HANDLER.tail_log(target_session)
        if log_output is None:
            user_feedback(f"No logs available for session '{target_session}'.")
            return
        if isinstance(log_output, (list, tuple)):
            for line in log_output:
                print(line)
        elif isinstance(log_output, str):
            # Print whole string — don't iterate character-by-character.
            print(log_output)
        else:
            # Generator / other iterable.
            try:
                for line in log_output:
                    print(line)
            except TypeError:
                print(log_output)
        return
    except Exception as e:
        logger.error(f"Error tailing logs for session '{target_session}': {e}", exc_info=True)
        user_feedback(f"Failed to get logs for session '{target_session}'. See logs for details.")
        return
