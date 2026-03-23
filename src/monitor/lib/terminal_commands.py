"""Uses global logging config; do not configure logging here."""

import subprocess
import os
import shutil
import platform
import logging
import shlex
from monitor.lib.screen_handler import ScreenHandler
from monitor.lib.screen_handler_utils import resolve_screen_token

# Set up a root-level logger
logger = logging.getLogger(__name__)

# Module-level default screen handler
_SCREEN_HANDLER = ScreenHandler()

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
            "Usage: :screen <subcommand> [args]\n\n"
            "Subcommands:\n"
            "  list, ls                    List active screen sessions\n"
            "  logs <session_name>         Show recent logs for a session\n"
            "  attach <session_name>       Attach to an existing session\n"
            "  kill <session_name>         Kill a session\n"
            "  send <session_name> [--] <text>  Send text to a session\n\n"
            "Examples:\n"
            "  :screen list\n"
            "  :screen logs mysession\n"
            "  :screen attach mysession\n"
            "  :screen kill mysession\n"
            "  :screen send mysession -- \"echo hello\"\n"
        )
        print(help_text)
        user_feedback("Displayed :screen usage information.")
        return

    if tokens:
        first = tokens[0]
        # Handle "list" / "ls" custom action via ScreenHandler
        if first in ("list", "ls"):
            try:
                sessions = _SCREEN_HANDLER.list_sessions()
                if sessions is None:
                    user_feedback("No screen sessions found.")
                    return

                # sessions may be a dict {name: state} or an iterable of (name, state)
                if isinstance(sessions, dict):
                    items = sessions.items()
                else:
                    items = sessions

                for item in items:
                    try:
                        name, state = item
                        print(f"{name} - {state}")
                    except Exception:
                        # Fallback if item is not a (name, state) pair
                        print(str(item))
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
