"""Spawn fallthrough: when the first token isn't a known subcommand,
treat the whole command string as a shell command to run in a new
detached screen session.

This is the original ``:agent <cmd>`` shape — kept for backward compat
even though subcommands now cover most use cases. The spawn path also
starts an OrchestratorPoller for the new session and registers it in
the orchestrator registry so :agent kill can clean it up later.
"""

import json
import logging
import subprocess
import threading
import uuid

from monitor.lib.screen_handler import ScreenHandlerError, SubagentCreationBlocked
from monitor.lib.terminal_commands_util import (
    is_executable_on_path,
    is_platform_unix,
    register_orchestrator_entry,
    user_feedback,
)

logger = logging.getLogger(__name__)


def agent_spawn(command):
    """Start a new detached screen session running ``command``.

    Prefers the high-level ``_SCREEN_HANDLER.create_interactive_subagent``
    path (which provides metadata + a status socket the orchestrator
    poller can watch). Falls back to a low-level ``screen -dm`` + ``stuff``
    sequence if the high-level call fails for any non-blocked reason.

    Returns a structured dict on the high-level success path, ``None``
    on legacy fallback or any error.
    """
    from monitor.lib.terminal_commands import _SCREEN_HANDLER

    session_name = "mysession"

    if not is_platform_unix():
        logger.error("run_command_in_screen is only supported on UNIX-like systems (Linux, macOS).")
        user_feedback("This feature is only available on UNIX-based systems (Linux, macOS).")
        return

    if not is_executable_on_path("screen"):
        logger.error("'screen' is not installed or not found in PATH. Cannot launch command in screen session.")
        user_feedback("Required tool 'screen' not found. Please install 'screen' to use this feature.")
        return

    try:
        try:
            subagent_info = _SCREEN_HANDLER.create_interactive_subagent(command)

            # Some handlers return (idx, payload); prefer the payload.
            if isinstance(subagent_info, (list, tuple)) and len(subagent_info) >= 2:
                subagent_info = subagent_info[1]

            # Normalize fields out of dict OR object. Defensive against
            # handler-shape evolution — kept verbatim from the original
            # monolithic implementation.
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
                session_name_ret = getattr(subagent_info, 'session_name', None) or getattr(subagent_info, 'name', None) or session_name
                metadata_path = getattr(subagent_info, 'metadata_path', None) or getattr(subagent_info, 'metadata', None) or getattr(subagent_info, 'meta_path', None)
                status_socket = getattr(subagent_info, 'status_socket', None) or getattr(subagent_info, 'status', None) or getattr(subagent_info, 'socket', None)
                token_val = getattr(subagent_info, 'token', None)
                screen_token_val = getattr(subagent_info, 'screen_token', None)
                screen_val = getattr(subagent_info, 'screen', None)

            user_feedback(f"Command '{command}' is running in screen session '{session_name_ret}'.")
            print(f"Session: {session_name_ret}")
            if metadata_path:
                user_feedback(f"Session metadata path: {metadata_path}")
                print(f"Metadata path: {metadata_path}")
            if status_socket:
                user_feedback(f"Session status socket: {status_socket}")
                print(f"Status socket: {status_socket}")

            logger.info(f"Created interactive subagent for command '{command}' in session '{session_name_ret}' with metadata '{metadata_path}' and status socket '{status_socket}'")

            # Normalize values to JSON-serializable types for the return dict.
            metadata_path = str(metadata_path) if metadata_path is not None else None
            status_socket = str(status_socket) if status_socket is not None else None
            token_val = str(token_val) if token_val is not None else None
            screen_token_val = str(screen_token_val) if screen_token_val is not None else None
            screen_val = str(screen_val) if screen_val is not None else None
            correlation_id = uuid.uuid4().hex[:12]

            result_dict = {
                'status': 'ok',
                'session_name': session_name_ret,
                'session': session_name_ret,
                'metadata_path': metadata_path,
                'status_socket': status_socket,
                'correlation_id': correlation_id,
            }
            if token_val:
                result_dict['token'] = token_val
            if screen_token_val:
                result_dict['screen_token'] = screen_token_val
            if screen_val:
                result_dict['screen'] = screen_val

            # If a status_socket is available, start an OrchestratorPoller to monitor it.
            if status_socket:
                _start_orchestrator_poller(session_name_ret, status_socket, token_val, screen_token_val, screen_val)

            return result_dict
        except SubagentCreationBlocked as e:
            # Handler explicitly blocked creation — surface and stop. Do NOT fall back.
            logger.info(f"create_interactive_subagent blocked: {e}")
            user_feedback(str(e))
            print(json.dumps({"status": "error", "message": str(e)}))
            return
        except Exception as e:
            logger.error(f"create_interactive_subagent failed: {e}", exc_info=True)
            user_feedback("Failed to create interactive subagent via ScreenHandler; falling back to legacy screen behavior.")

        # Legacy fallback: create a screen session, then `stuff` the command.
        create_result = subprocess.run(['screen', '-S', session_name, '-dm'], capture_output=True, text=True)
        if create_result.returncode != 0:
            logger.error(f"Failed to create screen session '{session_name}': {create_result.stderr.strip()}")
            user_feedback(f"Failed to create screen session '{session_name}'. See logs for details.")
            return

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


def _start_orchestrator_poller(session_name_ret, status_socket, token_val, screen_token_val, screen_val):
    """Start an OrchestratorPoller for a freshly-spawned session and
    register it under all known keys (session name + any token-like
    aliases) so :agent kill can find it by any of them later.

    Lazy-imports Queue and OrchestratorPoller so the spawn path doesn't
    pay the import cost when the spawn fails before reaching this point.
    """
    try:
        from queue import Queue
        from monitor.lib.orchestrator_poller import OrchestratorPoller

        q = Queue()
        try:
            poller = OrchestratorPoller(session_name_ret, status_socket, queue=q)
            # Prefer .start() (Thread subclass convention). Fall back to
            # spawning a daemon Thread around .run() if the poller didn't
            # provide a start() method.
            start_fn = getattr(poller, 'start', None)
            t = None
            if callable(start_fn):
                start_fn()
            else:
                run_fn = getattr(poller, 'run', None)
                if callable(run_fn):
                    t = threading.Thread(target=run_fn, name=f"OrchPoller-{session_name_ret}", daemon=True)
                    t.start()

            entry_obj = {'poller': poller, 'queue': q}
            if t is not None:
                entry_obj['thread'] = t

            # Build the dedup'd key list — session name plus any
            # token-like aliases so :agent kill <any-of-them> can find
            # the registered entry.
            keys = [k for k in (session_name_ret, token_val, screen_token_val, screen_val) if k]
            seen = set()
            filtered_keys = []
            for k in keys:
                if k not in seen:
                    seen.add(k)
                    filtered_keys.append(k)

            try:
                register_orchestrator_entry(entry_obj, filtered_keys)
            except Exception as e:
                logger.error(f"Failed to register orchestrator poller for session '{session_name_ret}': {e}", exc_info=True)
                user_feedback(f"Failed to start orchestrator poller for session '{session_name_ret}'. See logs for details.")
                return

            user_feedback(f"Orchestrator poller started for session '{session_name_ret}'.")
            logger.info(f"Orchestrator poller started for session '{session_name_ret}' monitoring socket '{status_socket}'")
            logger.info(f"Registered orchestrator poller keys: {filtered_keys} for session '{session_name_ret}'")
        except Exception as e:
            logger.error(f"Failed to instantiate/start OrchestratorPoller for session '{session_name_ret}': {e}", exc_info=True)
            user_feedback(f"Failed to start orchestrator poller for session '{session_name_ret}'. See logs for details.")
    except Exception as e:
        logger.error(f"Failed to import Queue/OrchestratorPoller for session '{session_name_ret}': {e}", exc_info=True)
        user_feedback(f"Orchestrator poller unavailable for session '{session_name_ret}'. See logs for details.")
