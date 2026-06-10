"""Help text for :agent (printed when invoked with no subcommand)."""

from monitor.lib.terminal_commands_util import user_feedback


_AGENT_HELP_TEXT = (
    "Usage: : (or /) agent <subcommand> [args]\n\n"
    "Subcommands:\n"
    "  list, ls                    List active agent sessions (supports per-instance numeric indices)\n"
    "                              Use --full to show tokens and metadata paths\n"
    "  logs <session_name|index>   Show recent logs for an agent (index resolves per-instance)\n"
    "  logfile <session_name|index> Print the logfile path for a session (index resolves per-instance)\n"
    "  attach <session_name|index> Attach to an existing agent (index resolves per-instance)\n"
    "  kill <session_name|index>   Kill an agent (index resolves per-instance)\n"
    "  send <session_name|index> [--] <text>  Send text to an agent (index resolves per-instance)\n\n"
    "Examples:\n"
    "  :agent list\n"
    "  :agent list --full\n"
    "  :agent logs mysession\n"
    "  :agent logs 3\n"
    "  :agent logfile mysession\n"
    "  :agent logfile 3\n"
    "  :agent attach mysession\n"
    "  :agent attach 2\n"
    "  :agent kill mysession\n"
    "  :agent kill 1\n"
    "  :agent send mysession -- \"echo hello\"\n"
    "  :agent send 4 \"echo hello\"\n"
)


def agent_usage() -> None:
    """Print the help block for :agent. Invoked when the command is
    typed with no subcommand args."""
    print(_AGENT_HELP_TEXT)
    user_feedback("Displayed :agent usage information.")
