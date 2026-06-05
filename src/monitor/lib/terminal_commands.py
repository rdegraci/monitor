"""Uses global logging config; do not configure logging here."""

import logging
import os
import platform
import shutil
import subprocess
import shlex
import uuid
import threading
import json
from monitor.lib.screen_handler import ScreenHandlerError, get_global_screen_handler, SubagentCreationBlocked
from monitor.lib.screen_handler_utils import resolve_screen_token
from monitor.lib import subagent_logging
from monitor.lib.terminal_commands_util import (
    _color,
    user_feedback,
    is_executable_on_path,
    is_platform_mac,
    is_platform_unix,
    register_orchestrator_entry,
    remove_orchestrator_entries_by_target,
)

# Set up a root-level logger
logger = logging.getLogger(__name__)

# Module-level default screen handler (lazy)
class _LazyScreen:
    """Lazy proxy for the global ScreenHandler.

    This proxy defers the construction/lookup of the actual global ScreenHandler
    until the first attribute access. It is thread-safe and forwards attribute
    access and method calls to the underlying handler returned by
    get_global_screen_handler().

    The intent is to avoid importing/constructing the real ScreenHandler at
    module-import time and instead obtain it on first use, preserving existing
    call sites which expect a handler object with standard attributes and
    methods.

    Attributes:
        _lock (threading.Lock): Lock protecting lazy initialization.
        _handler: The resolved ScreenHandler instance, or None until initialized.
    """

    def __init__(self):
        """Initialize the lazy proxy.

        Initializes the internal lock and leaves the underlying handler unset.
        """
        self._lock = threading.Lock()
        self._handler = None

    def _ensure(self):
        """Ensure the underlying ScreenHandler instance is initialized.

        If not already initialized, calls get_global_screen_handler() to obtain
        the real handler and caches it for subsequent attribute accesses.

        Raises:
            Exception: Propagates exceptions from get_global_screen_handler.
        """
        if self._handler is None:
            with self._lock:
                if self._handler is None:
                    self._handler = get_global_screen_handler()

    def __getattr__(self, name):
        """Forward attribute access to the underlying ScreenHandler.

        This method triggers initialization on first access.

        Args:
            name (str): Attribute name to retrieve.

        Returns:
            Any: The attribute from the underlying ScreenHandler.

        Raises:
            AttributeError: If the underlying handler doesn't have the attribute.
            Exception: Propagated exceptions from initialization.
        """
        self._ensure()
        return getattr(self._handler, name)

    def __repr__(self):
        """Return a representation for debugging purposes."""
        if self._handler is None:
            return "<_LazyScreen(uninitialized)>"
        return repr(self._handler)

_SCREEN_HANDLER = _LazyScreen()

# Registry of active orchestrator pollers keyed by session name.
# Each entry is a dict with keys:
#   - 'poller': the poller object
#   - 'queue': the Queue instance used by the poller
# This registry is managed at runtime; entries are added when a subagent with a
# status_socket is created and removed when the corresponding session is killed.
# Note: The in-memory registry is managed via helper functions in terminal_commands_util
# (register_orchestrator_entry/remove_orchestrator_entries_by_target) rather than
# local module-level structures.

def _resolve_index_to_session_name(token):
    """Resolve a numeric session index to the actual session name via ScreenHandler.

    This function supports ScreenHandler.get_session_by_index returning either a
    simple session name (str) or a dict-like session entry. If a dict is returned,
    the function will attempt to extract the 'session_name', 'name', or 'session'
    key from the dict.

    Args:
        token (str): Token provided by the user; if numeric, attempt to resolve.

    Returns:
        str: The resolved session name.

    Raises:
        ScreenHandlerError: If ScreenHandler.get_session_by_index raises ScreenHandlerError.
        Exception: If no session is found for the given index or other errors occur.
    """
    if not str(token).isdigit():
        return token
    idx = int(token)
    # ScreenHandler is expected to provide a method get_session_by_index
    session_entry = None
    try:
        session_entry = _SCREEN_HANDLER.get_session_by_index(idx)
    except ScreenHandlerError:
        # Propagate ScreenHandler-specific errors for the caller to handle appropriately.
        raise
    except Exception:
        # Let caller handle other exceptions and user feedback/logging
        raise

    session_name = None

    # If handler returned a dict-like entry, attempt to extract the session name.
    if isinstance(session_entry, dict):
        session_name = session_entry.get('session_name') or session_entry.get('name') or session_entry.get('session')
    elif isinstance(session_entry, tuple) and len(session_entry) >= 2:
        # Some handlers may return (index, payload)
        payload = session_entry[1]
        if isinstance(payload, dict):
            session_name = payload.get('session_name') or payload.get('name') or payload.get('session')
        else:
            session_name = getattr(payload, 'session_name', None) or getattr(payload, 'name', None) or (str(payload) if isinstance(payload, str) else None)
    else:
        if isinstance(session_entry, str):
            session_name = session_entry
        else:
            session_name = getattr(session_entry, 'session_name', None) or getattr(session_entry, 'name', None) or getattr(session_entry, 'session', None)

    if not session_name:
        raise Exception(f"No session found for index {idx}")
    return session_name

# The Terminal application’s permissions must be configured to allow AppleScript automation on your Mac. 
# You can adjust these settings under `System Preferences > Security & Privacy > Privacy > Automation`.
def run_command_in_terminal(command):
    """Run the specified shell command in a new Terminal window via AppleScript on macOS.

    Args:
        command (str): The shell command to execute.

    Returns:
        None

    Notes:
        - Requires that 'osascript' is available (i.e., on macOS).
        - Terminal app may need automation permissions to work via AppleScript.
        - Errors are logged; function returns gracefully on failure.
    """
    # Check for platform compatibility
    if not is_platform_mac():
        logger.error("run_command_in_terminal is only supported on macOS.")
        user_feedback("This feature is only available on macOS.")
        return

    if not is_executable_on_path("osascript"):
        logger.error("'osascript' is not available on this system. AppleScript-based terminal automation is unavailable.")
        user_feedback("Required tool 'osascript' not found. Please ensure you are running on macOS with AppleScript support.")
        return

    applescript_command = f'''
    tell application "Terminal"
        do script "{command}"
        activate
    end tell
    '''
    try:
        result = subprocess.run(['osascript', '-e', applescript_command], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"AppleScript (osascript) command failed: {result.stderr.strip()}")
            user_feedback("Failed to open Terminal window or run the command. See logs for details.")
        else:
            logger.info(f"Successfully ran AppleScript to execute command in Terminal: {command}")
    except Exception as e:
        logger.error(f"Exception while executing AppleScript: {e}", exc_info=True)
        user_feedback("An unexpected error occurred while trying to run the command in Terminal. Please check logs for details.")


def run_command_in_screen(command):
    """Thin entry point that delegates to the monitor.lib.agent dispatcher.

    The :agent built-in's seven subcommands (list / logs / logfile /
    attach / kill / send + spawn fallthrough) used to live inside this
    function as a ~740-line if/elif maze. They now live one-per-file
    under monitor.lib.agent — see that package for the actual logic.

    The lazy import keeps terminal_commands.py free of any module-level
    dependency on the agent package (the agent modules import
    _SCREEN_HANDLER and _resolve_index_to_session_name back from this
    module), which is the standard fix for the circular-import shape.

    Args:
        command (str): User-typed argument string after ``:agent``.

    Returns:
        Whatever the dispatcher returns — typically None for subcommands,
        a structured dict for the spawn path on success.
    """
    from monitor.lib.agent.dispatcher import dispatch
    return dispatch(command)


def _RUN_COMMAND_IN_SCREEN_LEGACY_NOTE():
    """Historical anchor (no-op). The previous monolithic
    run_command_in_screen body was extracted to monitor.lib.agent during
    a 2026-Q2 refactor. Tests in tests/monitor/lib/test_terminal_commands.py
    that monkeypatch ``terminal_commands._SCREEN_HANDLER`` continue to
    work because that object lives here, not in the new package; the
    subcommand modules import it from this module."""
    return None


def __OLD_LEGACY_BODY_REMOVED__():
    session_name = "mysession"
    try:
        tokens = shlex.split(command or "")
    except Exception as e:
        logger.error(f"Failed to parse command string '{command}': {e}", exc_info=True)
        user_feedback("Failed to parse the provided command. See logs for details.")
        return

    # If invoked with no arguments, print concise usage help and return
    if not tokens:
        help_text = (
            "Usage: :agent <subcommand> [args]\n\n"
            "Subcommands:\n"
            "  list, ls                    List active agent sessions (supports per-instance numeric indices)\n"
            "                              Use --full to show tokens and metadata paths\n"
            "  logs <session_name|index>   Show recent logs for a agent (index resolves per-instance)\n"
            "  logfile <session_name|index> Print the logfile path for a session (index resolves per-instance)\n"
            "  attach <session_name|index> Attach to an existing agent (index resolves per-instance)\n"
            "  kill <session_name|index>   Kill a agent (index resolves per-instance)\n"
            "  send <session_name|index> [--] <text>  Send text to a agent (index resolves per-instance)\n\n"
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
        print(help_text)
        user_feedback("Displayed :agent usage information.")
        return

    if tokens:
        first = tokens[0]
        # Handle "list" / "ls" custom action via ScreenHandler
        if first in ("list", "ls"):
            # detect --full flag
            full = '--full' in tokens
            try:
                # Prefer the new API that supports per-instance indices and full metadata
                try:
                    sessions = _SCREEN_HANDLER.list_indexed_sessions(full=full)
                except AttributeError:
                    # Fallback if the handler doesn't implement the new API
                    sessions = _SCREEN_HANDLER.list_sessions()
                    full = False  # can't show full details if method absent

                if sessions is None:
                    user_feedback("No screen sessions found.")
                    return

                # Prepare rows with normalized fields
                rows = []
                # Attempt to determine instance id and sessions file for header
                instance_id = getattr(_SCREEN_HANDLER, 'instance_id', None)
                sessions_file = getattr(_SCREEN_HANDLER, 'sessions_file', None)

                def _extract_info(item):
                    """Normalize a single item into a dict with expected keys."""
                    info = {}
                    # item might be (index, payload), dict, or object
                    if isinstance(item, tuple) and len(item) == 2 and (isinstance(item[0], (int, str))):
                        idx = item[0]
                        payload = item[1]
                    else:
                        payload = item
                        idx = None

                    if isinstance(payload, dict):
                        info['index'] = idx if idx is not None else payload.get('index') or payload.get('idx')
                        info['name'] = payload.get('name') or payload.get('session_name') or payload.get('session')
                        info['token'] = payload.get('token') or payload.get('screen_token') or payload.get('screen')
                        info['state'] = payload.get('state') or payload.get('status')
                        info['created_at'] = payload.get('created_at') or payload.get('created') or payload.get('ctime')
                        info['meta_path'] = payload.get('meta_path') or payload.get('metadata_path') or payload.get('metadata')
                    else:
                        # Generic object or simple value
                        info['index'] = idx if idx is not None else getattr(payload, 'index', None) or getattr(payload, 'idx', None)
                        info['name'] = getattr(payload, 'name', None) or getattr(payload, 'session_name', None) or (str(payload) if isinstance(payload, str) else None)
                        info['token'] = getattr(payload, 'token', None) or getattr(payload, 'screen_token', None)
                        info['state'] = getattr(payload, 'state', None) or getattr(payload, 'status', None)
                        info['created_at'] = getattr(payload, 'created_at', None) or getattr(payload, 'created', None)
                        info['meta_path'] = getattr(payload, 'meta_path', None) or getattr(payload, 'metadata_path', None) or getattr(payload, 'metadata', None)
                    # Normalize to strings for display
                    for k in ['index', 'name', 'token', 'state', 'created_at', 'meta_path']:
                        if info.get(k) is None:
                            info[k] = ""
                    return info

                # Determine iterable type
                if isinstance(sessions, dict):
                    iterable = sessions.items()
                else:
                    iterable = sessions

                for item in iterable:
                    try:
                        info = _extract_info(item)
                        rows.append(info)
                    except Exception:
                        # Best-effort: fallback to string representation
                        rows.append({
                            'index': '',
                            'name': str(item),
                            'token': '',
                            'state': '',
                            'created_at': '',
                            'meta_path': ''
                        })

                # Compute column widths
                idx_width = max([len(str(r['index'])) for r in rows] + [5])
                name_width = max([len(r['name'] or "") for r in rows] + [12])
                token_width = max([len(r['token'] or "") for r in rows] + ([10] if full else [0]))
                state_width = max([len(r['state'] or "") for r in rows] + [6])
                created_width = max([len(r['created_at'] or "") for r in rows] + [10])
                meta_width = max([len(r['meta_path'] or "") for r in rows] + ([12] if full else [0]))

                # Print header with instance info and sessions file basename if available
                header_line = "Sessions"
                if instance_id:
                    header_line += f" (instance: {instance_id})"
                print(header_line)
                if sessions_file:
                    try:
                        print(f"Sessions file: {os.path.basename(sessions_file)}")
                    except Exception:
                        # If sessions_file is not a path-like string, just print representation
                        print(f"Sessions file: {sessions_file}")

                # Print table header
                if full:
                    header_fmt = f"{{:<{idx_width}}}  {{:<{name_width}}}  {{:<{token_width}}}  {{:<{state_width}}}  {{:<{created_width}}}  {{:<{meta_width}}}"
                    print(header_fmt.format("Index", "Name", "Token", "State", "Created", "Meta"))
                    print("-" * (idx_width + name_width + token_width + state_width + created_width + meta_width + 10))
                    for r in rows:
                        state_text = r['state'] or ""
                        st_lower = (state_text or "").lower()
                        if "run" in st_lower or "attached" in st_lower or "up" in st_lower:
                            color = "green"
                        elif "detach" in st_lower or "detached" in st_lower:
                            color = "yellow"
                        elif "dead" in st_lower or "exit" in st_lower or "exited" in st_lower or "stop" in st_lower:
                            color = "red"
                        else:
                            color = "blue"
                        state_colored = _color(state_text, color)
                        print(header_fmt.format(str(r['index']), r['name'], r['token'], state_colored, r['created_at'], r['meta_path']))
                else:
                    header_fmt = f"{{:<{idx_width}}}  {{:<{name_width}}}  {{:<{state_width}}}  {{:<{created_width}}}"
                    print(header_fmt.format("Index", "Name", "State", "Created"))
                    print("-" * (idx_width + name_width + state_width + created_width + 6))
                    for r in rows:
                        state_text = r['state'] or ""
                        st_lower = (state_text or "").lower()
                        if "run" in st_lower or "attached" in st_lower or "up" in st_lower:
                            color = "green"
                        elif "detach" in st_lower or "detached" in st_lower:
                            color = "yellow"
                        elif "dead" in st_lower or "exit" in st_lower or "exited" in st_lower or "stop" in st_lower:
                            color = "red"
                        else:
                            color = "blue"
                        state_colored = _color(state_text, color)
                        print(header_fmt.format(str(r['index']), r['name'], state_colored, r['created_at']))
                return
            except Exception as e:
                logger.error(f"Error listing screen sessions: {e}", exc_info=True)
                user_feedback("Failed to list screen sessions. See logs for details.")
                return

        # Handle "logs <session_name>" custom action via ScreenHandler
        if first == "logs":
            if len(tokens) < 2:
                user_feedback("Usage: logs <session_name>")
                return
            target_session = tokens[1]
            # Resolve numeric index tokens to session names
            if str(target_session).isdigit():
                try:
                    target_session = _resolve_index_to_session_name(target_session)
                except Exception as e:
                    logger.error(f"Error resolving session index '{tokens[1]}': {e}", exc_info=True)
                    user_feedback(f"Failed to resolve session index '{tokens[1]}'. See logs for details.")
                    return
            try:
                log_output = _SCREEN_HANDLER.tail_log(target_session)
                # If tail_log returns an iterable of lines, print them; otherwise, print the object
                if log_output is None:
                    user_feedback(f"No logs available for session '{target_session}'.")
                    return
                if isinstance(log_output, (list, tuple)):
                    for line in log_output:
                        print(line)
                else:
                    # Fix: Avoid iterating strings character-by-character by checking for str explicitly.
                    # Preserve existing behavior for lists/tuples and iterables (generators); print strings whole.
                    if isinstance(log_output, str):
                        print(log_output)
                    else:
                        try:
                            for line in log_output:
                                print(line)
                        except TypeError:
                            # Not iterable, just print directly
                            print(log_output)
                return
            except Exception as e:
                logger.error(f"Error tailing logs for session '{target_session}': {e}", exc_info=True)
                user_feedback(f"Failed to get logs for session '{target_session}'. See logs for details.")
                return

        # Handle "logfile <session_name>" custom action to locate the logfile for a session
        # This uses monitor.lib.subagent_logging.find_logfile_for_session_name to resolve the path.
        # Args:
        #   tokens: token list where tokens[1] is session name or numeric index.
        # Behavior:
        #   Resolve numeric indices to session names, call the helper to find the logfile path,
        #   print only the path if found, otherwise provide user feedback.
        if first == "logfile":
            if len(tokens) < 2:
                user_feedback("Usage: logfile <session_name>")
                return
            target_session = tokens[1]
            # Resolve numeric index tokens to session names
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
                    # Print only the path to be machine-friendly
                    print(logfile_path)
                    return
                else:
                    user_feedback(f"No logfile found for session '{target_session}'.")
                    return
            except Exception as e:
                logger.error(f"Error finding logfile for session '{target_session}': {e}", exc_info=True)
                user_feedback(f"Failed to get logfile for session '{target_session}'. See logs for details.")
                return

        # Handle "attach <session_name>" to attach to an existing screen session using 'screen -r <session>'
        if first == "attach":
            if len(tokens) < 2:
                user_feedback("Usage: attach <session_name>")
                return
            target_session = tokens[1]
            # Resolve numeric index tokens to session names
            if str(target_session).isdigit():
                try:
                    target_session = _resolve_index_to_session_name(target_session)
                except Exception as e:
                    logger.error(f"Error resolving session index '{tokens[1]}': {e}", exc_info=True)
                    user_feedback(f"Failed to resolve session index '{tokens[1]}'. See logs for details.")
                    return
            try:
                # Attempt to attach to the session; do not capture output so it attaches to the current TTY
                # Resolve the provided token to an actual screen token if possible using the ScreenHandler helper.
                try:
                    resolved_token = resolve_screen_token(_SCREEN_HANDLER.screen_cmd, target_session)
                except Exception as e:
                    logger.error(f"Error resolving screen token for '{target_session}': {e}", exc_info=True)
                    resolved_token = None

                token_to_use = resolved_token if resolved_token else target_session
                logger.info(f"Attaching to screen session token: '{token_to_use}'")

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

        # Handle "kill <session_name>" via ScreenHandler.kill_session
        if first == "kill":
            if len(tokens) < 2:
                user_feedback("Usage: kill <session_name>")
                return
            target_session = tokens[1]
            # Resolve numeric index tokens to session names
            if str(target_session).isdigit():
                try:
                    target_session = _resolve_index_to_session_name(target_session)
                except Exception as e:
                    logger.error(f"Error resolving session index '{tokens[1]}': {e}", exc_info=True)
                    user_feedback(f"Failed to resolve session index '{tokens[1]}'. See logs for details.")
                    return
            try:
                result = _SCREEN_HANDLER.kill_session(target_session)
                if result:
                    user_feedback(f"Successfully killed screen session '{target_session}'.")
                    logger.info(f"Killed screen session '{target_session}'.")
                    # Orchestrator cleanup: tell the registry to remove and
                    # stop any pollers registered under this session key.
                    # The helper handles stop() + join() internally; we
                    # only need to count the removed entries for logging.
                    # Documented return shape: Dict[str, List[entry_dict]]
                    # — trust it instead of defensively decoding every
                    # possible shape.
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
                else:
                    user_feedback(f"Failed to kill screen session '{target_session}'. See logs for details.")
                    logger.error(f"kill_session returned falsy for session '{target_session}'.")
                return
            except Exception as e:
                logger.error(f"Error killing screen session '{target_session}': {e}", exc_info=True)
                user_feedback(f"Failed to kill screen session '{target_session}'. See logs for details.")
                return

        # Handle "send <session> -- <text>" or "send <session> <text>" via ScreenHandler.send_to_session
        if first == "send":
            if len(tokens) < 3:
                user_feedback("Usage: send <session_name> [--] <text>")
                return
            target_session = tokens[1]
            # Resolve numeric index tokens to session names
            if str(target_session).isdigit():
                try:
                    target_session = _resolve_index_to_session_name(target_session)
                except Exception as e:
                    logger.error(f"Error resolving session index '{tokens[1]}': {e}", exc_info=True)
                    user_feedback(f"Failed to resolve session index '{tokens[1]}'. See logs for details.")
                    return
            # Extract text after '--' if present; otherwise everything after the session name
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

    # If not a special local action, proceed with original behavior

    # Check for platform compatibility
    if not is_platform_unix():
        logger.error("run_command_in_screen is only supported on UNIX-like systems (Linux, macOS).")
        user_feedback("This feature is only available on UNIX-based systems (Linux, macOS).")
        return

    if not is_executable_on_path("screen"):
        logger.error("'screen' is not installed or not found in PATH. Cannot launch command in screen session.")
        user_feedback("Required tool 'screen' not found. Please install 'screen' to use this feature.")
        return

    try:
        # Attempt to create an interactive subagent via ScreenHandler which provides metadata and a status socket.
        # If this fails for any reason, fall back to the legacy behavior of creating a detached screen session
        # and stuffing the command into it.
        try:
            subagent_info = _SCREEN_HANDLER.create_interactive_subagent(command)

            # If handler returned a (idx, payload) style tuple/list, prefer the payload element
            if isinstance(subagent_info, (list, tuple)) and len(subagent_info) >= 2:
                subagent_info = subagent_info[1]

            # Normalize returned information into session_name, metadata_path, status_socket where possible.
            session_name_ret = None
            metadata_path = None
            status_socket = None
            token_val = None
            screen_token_val = None
            screen_val = None

            if isinstance(subagent_info, dict):
                session_name_ret = subagent_info.get('session_name') or subagent_info.get('name') or session_name
                metadata_path = subagent_info.get('metadata_path') or subagent_info.get('metadata') or subagent_info.get('meta_path')
                status_socket = subagent_info.get('status_socket') or subagent_info.get('status') or subagent_info.get('socket')
                token_val = subagent_info.get('token') if 'token' in subagent_info else None
                screen_token_val = subagent_info.get('screen_token') if 'screen_token' in subagent_info else None
                screen_val = subagent_info.get('screen') if 'screen' in subagent_info else None
            else:
                # Fallback to attribute access for objects
                session_name_ret = getattr(subagent_info, 'session_name', None) or getattr(subagent_info, 'name', None) or session_name
                metadata_path = getattr(subagent_info, 'metadata_path', None) or getattr(subagent_info, 'metadata', None) or getattr(subagent_info, 'meta_path', None)
                status_socket = getattr(subagent_info, 'status_socket', None) or getattr(subagent_info, 'status', None) or getattr(subagent_info, 'socket', None)
                token_val = getattr(subagent_info, 'token', None)
                screen_token_val = getattr(subagent_info, 'screen_token', None)
                screen_val = getattr(subagent_info, 'screen', None)

            # Inform the user and print relevant metadata paths
            user_feedback(f"Command '{command}' is running in screen session '{session_name_ret}'.")
            print(f"Session: {session_name_ret}")
            if metadata_path:
                user_feedback(f"Session metadata path: {metadata_path}")
                print(f"Metadata path: {metadata_path}")
            if status_socket:
                user_feedback(f"Session status socket: {status_socket}")
                print(f"Status socket: {status_socket}")

            logger.info(f"Created interactive subagent for command '{command}' in session '{session_name_ret}' with metadata '{metadata_path}' and status socket '{status_socket}'")

            # Normalize values to JSON-serializable types
            metadata_path = str(metadata_path) if metadata_path is not None else None
            status_socket = str(status_socket) if status_socket is not None else None
            token_val = str(token_val) if token_val is not None else None
            screen_token_val = str(screen_token_val) if screen_token_val is not None else None
            screen_val = str(screen_val) if screen_val is not None else None
            correlation_id = uuid.uuid4().hex[:12]

            # Build structured return dict including any token-like fields if present
            result_dict = {
                'status': 'ok',
                'session_name': session_name_ret,
                'session': session_name_ret,
                'metadata_path': metadata_path,
                'status_socket': status_socket,
                'correlation_id': correlation_id
            }
            if token_val:
                result_dict['token'] = token_val
            if screen_token_val:
                result_dict['screen_token'] = screen_token_val
            if screen_val:
                result_dict['screen'] = screen_val

            # If a status_socket is available, try to start an OrchestratorPoller to monitor it.
            if status_socket:
                try:
                    # Lazy import of Queue and OrchestratorPoller to avoid hard dependency at module import time.
                    from queue import Queue  # standard library
                    from monitor.lib.orchestrator_poller import OrchestratorPoller
                    q = Queue()
                    try:
                        poller = OrchestratorPoller(session_name_ret, status_socket, queue=q)
                        # Start the poller if it exposes a start() method (typical for threading.Thread subclasses).
                        start_fn = getattr(poller, 'start', None)
                        t = None
                        if callable(start_fn):
                            start_fn()
                        else:
                            # If no start(), attempt to call run() in a background thread.
                            run_fn = getattr(poller, 'run', None)
                            if callable(run_fn):
                                t = threading.Thread(target=run_fn, name=f"OrchPoller-{session_name_ret}", daemon=True)
                                t.start()
                                # If the poller needs to be referenced, wrap it with a small adapter object.
                                poller = poller  # keep original reference
                        # Register the poller for later cleanup when the session is killed.
                        entry_obj = {'poller': poller, 'queue': q}
                        if t is not None:
                            entry_obj['thread'] = t
                        registered_keys = []
                        try:
                            # Register under session_name_ret and any available token-like keys.
                            # Use a guarded approach to compute keys first, then call the registration helper.
                            keys = []
                            try:
                                # add token-like keys if present and truthy
                                if session_name_ret:
                                    keys.append(session_name_ret)
                                if token_val:
                                    keys.append(token_val)
                                if screen_token_val:
                                    keys.append(screen_token_val)
                                if screen_val:
                                    keys.append(screen_val)
                            except Exception:
                                # In case of unexpected issues reading locals, proceed with the primary key only
                                keys = [session_name_ret]

                            # Filter only truthy keys and remove duplicates while preserving order
                            seen = set()
                            filtered_keys = []
                            for k in keys:
                                try:
                                    if not k:
                                        continue
                                    if k in seen:
                                        continue
                                    seen.add(k)
                                    filtered_keys.append(k)
                                except Exception:
                                    # If key is unhashable, include it and continue
                                    try:
                                        if k not in filtered_keys:
                                            filtered_keys.append(k)
                                    except Exception:
                                        continue

                            # Call the registration helper. Try both common parameter orders to be robust.
                            reg_result = None
                            try:
                                reg_result = register_orchestrator_entry(entry_obj, filtered_keys)
                            except TypeError:
                                # Try swapping the parameter order
                                reg_result = register_orchestrator_entry(filtered_keys, entry_obj)
                            except Exception as e:
                                # If registration failed, log and continue without raising.
                                logger.error(f"Failed to register orchestrator poller for session '{session_name_ret}': {e}", exc_info=True)
                                reg_result = None

                            # Interpret registration result if present
                            if reg_result:
                                try:
                                    if isinstance(reg_result, (list, tuple)):
                                        registered_keys = list(reg_result)
                                    elif isinstance(reg_result, dict):
                                        registered_keys = list(reg_result.keys())
                                    elif isinstance(reg_result, str):
                                        registered_keys = [reg_result]
                                except Exception:
                                    # Ignore interpretation errors; leave registered_keys empty if we cannot parse it
                                    registered_keys = []

                            user_feedback(f"Orchestrator poller started for session '{session_name_ret}'.")
                            logger.info(f"Orchestrator poller started for session '{session_name_ret}' monitoring socket '{status_socket}'")
                            try:
                                logger.info(f"Registered orchestrator poller keys: {registered_keys} for session '{session_name_ret}'")
                            except Exception:
                                pass
                        except Exception as e:
                            logger.error(f"Failed to register orchestrator poller for session '{session_name_ret}': {e}", exc_info=True)
                            user_feedback(f"Failed to start orchestrator poller for session '{session_name_ret}'. See logs for details.")
                    except Exception as e:
                        logger.error(f"Failed to instantiate/start OrchestratorPoller for session '{session_name_ret}': {e}", exc_info=True)
                        user_feedback(f"Failed to start orchestrator poller for session '{session_name_ret}'. See logs for details.")
                except Exception as e:
                    logger.error(f"Failed to import Queue/OrchestratorPoller for session '{session_name_ret}': {e}", exc_info=True)
                    user_feedback(f"Orchestrator poller unavailable for session '{session_name_ret}'. See logs for details.")

            return result_dict
        except SubagentCreationBlocked as e:
            # If the ScreenHandler explicitly blocks subagent creation, inform the user and do not fall back.
            logger.info(f"create_interactive_subagent blocked: {e}")
            user_feedback(str(e))
            print(json.dumps({"status":"error","message": str(e)}))
            return
        except Exception as e:
            # If ScreenHandler.create_interactive_subagent fails, log and fall back to legacy behavior.
            logger.error(f"create_interactive_subagent failed: {e}", exc_info=True)
            user_feedback("Failed to create interactive subagent via ScreenHandler; falling back to legacy screen behavior.")

        # Legacy fallback: create a screen session with the provided session name
        create_result = subprocess.run(['screen', '-S', session_name, '-dm'], capture_output=True, text=True)
        if create_result.returncode != 0:
            logger.error(f"Failed to create screen session '{session_name}': {create_result.stderr.strip()}")
            user_feedback(f"Failed to create screen session '{session_name}'. See logs for details.")
            return

        # Run the command within the newly created screen session
        stuff_result = subprocess.run(['screen', '-S', session_name, '-X', 'stuff', f'{command}\n'], capture_output=True, text=True)
        if stuff_result.returncode != 0:
            logger.error(f"Failed to send command to screen session '{session_name}': {stuff_result.stderr.strip()}")
            user_feedback(f"Failed to send command to screen session '{session_name}'. See logs for details.")
            return

        logger.info(f"Command '{command}' is running in screen session '{session_name}'.")
        user_feedback(f"Command '{command}' is running in screen session '{session_name}'.")
    except Exception as e:
        logger.error(f"Exception while trying to launch command in screen session: {e}", exc_info=True)
        user_feedback("An error occurred while launching the screen session. Please check logs for details.")


# End of file.
