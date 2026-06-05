"""Dispatch :agent subcommands to the right handler.

The public entry point is ``dispatch(command)``, which parses the raw
user-typed argument string via ``shlex.split`` and routes to one of the
per-subcommand modules. An unrecognized first token prints a usage error
(it does NOT spawn anything — sub-agents are created only through the
safeguarded ``agent_create`` LLM tool, which enforces the orchestration
gate and breadth/total caps).
"""

import logging
import shlex

from monitor.lib.terminal_commands_util import user_feedback

from monitor.lib.agent.attach import agent_attach
from monitor.lib.agent.kill import agent_kill
from monitor.lib.agent.list import agent_list
from monitor.lib.agent.logfile import agent_logfile
from monitor.lib.agent.logs import agent_logs
from monitor.lib.agent.send import agent_send
from monitor.lib.agent.usage import agent_usage

logger = logging.getLogger(__name__)


# Subcommand → handler dispatch table. Kept module-level so the routing
# is auditable at a glance: every supported :agent subcommand appears as
# one entry. ``list`` and ``ls`` are aliases for the same handler — same
# pattern as :llm / :model in built_ins.py.
_SUBCOMMAND_HANDLERS = {
    "list": agent_list,
    "ls": agent_list,
    "logs": agent_logs,
    "logfile": agent_logfile,
    "attach": agent_attach,
    "kill": agent_kill,
    "send": agent_send,
}


def dispatch(command):
    """Parse the user's argument string and route to the right handler.

    Args:
        command (str): Whatever the user typed after ``:agent``. Parsed
            via shlex.split so quoted strings survive intact.

    Returns:
        Whatever the routed handler returns (handlers return None).
    """
    try:
        tokens = shlex.split(command or "")
    except Exception as e:
        logger.error(f"Failed to parse command string '{command}': {e}", exc_info=True)
        user_feedback("Failed to parse the provided command. See logs for details.")
        return

    if not tokens:
        return agent_usage()

    first = tokens[0]
    handler = _SUBCOMMAND_HANDLERS.get(first)
    if handler is not None:
        return handler(tokens)

    # Unrecognized subcommand: report and show usage. We do NOT spawn here —
    # the old `:agent <cmd>` fallthrough was removed because it bypassed the
    # orchestration gate and the breadth/total caps, and turned typos (e.g.
    # `:agent listt`) into stray sessions.
    print(f"Unknown :agent subcommand: {first!r}\n")
    user_feedback(f"Unknown :agent subcommand: {first!r}")
    return agent_usage()
