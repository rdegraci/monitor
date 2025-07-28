
"""Uses global logging config; do not configure logging here."""

import subprocess
import os
import shutil
import platform
import logging

# Set up a root-level logger
logger = logging.getLogger(__name__)

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


def run_command_in_screen(command, session_name="mysession"):
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
        # Create a screen session with the provided session name
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
