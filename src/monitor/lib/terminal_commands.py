"""Terminal-launch helpers for Monitor.

After the 2026-Q2 :agent refactor this module only contains:

- ``run_command_in_terminal``  — macOS Terminal.app via AppleScript
- ``run_command_in_screen``    — thin delegator to monitor.lib.agent
- ``_resolve_index_to_session_name`` — shared helper for index→name resolution
- ``_LazyScreen`` / ``_SCREEN_HANDLER`` — lazy global ScreenHandler proxy

The :agent subcommand bodies (list / logs / logfile / attach / kill /
send / spawn / usage) used to live here in one ~740-line function;
they're now one-per-file under ``monitor.lib.agent.*`` and called via
the dispatcher.

Logging config: this module uses the global logger only — do not
configure logging here.
"""

import logging
import subprocess
import threading
from monitor.lib.screen_handler import ScreenHandlerError, get_global_screen_handler
from monitor.lib.terminal_commands_util import (
    user_feedback,
    is_executable_on_path,
    is_platform_mac,
    is_platform_unix,  # noqa: F401 — re-exported for tests/callers that still import via this module
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
