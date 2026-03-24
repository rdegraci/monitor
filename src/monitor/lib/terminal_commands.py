"""Uses global logging config; do not configure logging here."""

import subprocess
import os
import shutil
import platform
import logging
import shlex
from monitor.lib.screen_handler import ScreenHandler, ScreenHandlerError
from monitor.lib.screen_handler_utils import resolve_screen_token

# Set up a root-level logger
logger = logging.getLogger(__name__)

# Module-level default screen handler
_SCREEN_HANDLER = ScreenHandler()

def _color(text, color):
    """Return text wrapped in ANSI color codes.

    Args:
        text (str): Text to colorize.
        color (str): One of "green", "yellow", "red", "blue", "magenta", "reset".

    Returns:
        str: Colorized text using ANSI escape sequences if supported.
    """
    colors = {
        "reset": "\033[0m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
    }
    prefix = colors.get(color, "")
    suffix = colors.get("reset", "")
    if not prefix:
        return text
    return f"{prefix}{text}{suffix}"

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

def user_feedback(message):
    """UX helper for user-facing feedback; currently logs as INFO.

    Args:
        message (str): The message to deliver to the user.
    """
    logger.info(message)

def is_executable_on_path(executable):
    """Check if an executable exists on the current system PATH.

    Args:
        executable (str): The executable name to check.

    Returns:
        bool: True if found, False otherwise.
    """
    return shutil.which(executable) is not None

def is_platform_mac():
    """Check if the current platform is macOS.

    Returns:
        bool: True if running on macOS, False otherwise.
    """
    return platform.system() == "Darwin"

def is_platform_unix():
    """Check if the current platform is UNIX-like (Linux or Darwin).

    Returns:
        bool: True if running on a UNIX-like system, False otherwise.
    """
    return platform.system() in ("Linux", "Darwin")

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
    """Run a specified command in a detached GNU screen session.

    Args:
        command (str): The shell command to execute in the new screen session.
        session_name (str, optional): The name for the screen session. Defaults to "mysession".

    Returns:
        None

    Notes:
        - Requires 'screen' to be installed and available in the system PATH.
        - Only works on UNIX-like operating systems.
        - Logs all errors, does not raise exceptions on missing dependencies or runtime errors.
    """
    # Parse the incoming command for local helper actions first
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
            "  attach <session_name|index> Attach to an existing agent (index resolves per-instance)\n"
            "  kill <session_name|index>   Kill a agent (index resolves per-instance)\n"
            "  send <session_name|index> [--] <text>  Send text to a agent (index resolves per-instance)\n\n"
            "Examples:\n"
            "  :agent list\n"
            "  :agent list --full\n"
            "  :agent logs mysession\n"
            "  :agent logs 3\n"
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
                    # Could be a generator or a single string; handle generator by iterating
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

            # Normalize returned information into session_name, metadata_path, status_socket where possible.
            session_name_ret = None
            metadata_path = None
            status_socket = None

            if isinstance(subagent_info, dict):
                session_name_ret = subagent_info.get('session_name') or subagent_info.get('name') or session_name
                metadata_path = subagent_info.get('metadata_path') or subagent_info.get('metadata') or subagent_info.get('meta_path')
                status_socket = subagent_info.get('status_socket') or subagent_info.get('status') or subagent_info.get('socket')
            else:
                # Fallback to attribute access for objects
                session_name_ret = getattr(subagent_info, 'session_name', None) or getattr(subagent_info, 'name', None) or session_name
                metadata_path = getattr(subagent_info, 'metadata_path', None) or getattr(subagent_info, 'metadata', None) or getattr(subagent_info, 'meta_path', None)
                status_socket = getattr(subagent_info, 'status_socket', None) or getattr(subagent_info, 'status', None) or getattr(subagent_info, 'socket', None)

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
