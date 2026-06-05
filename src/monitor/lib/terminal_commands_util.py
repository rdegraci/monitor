"""Utility helpers extracted from terminal_commands.py.

This module contains pure helper functions that do not depend on the
module-level ScreenHandler state. They were moved here to keep
terminal_commands.py focused on screen-related behavior and to reduce
file size.
"""

import logging
import platform
import shutil
import threading
from typing import Any, Dict, List, Optional, Mapping

# Set up a module-level logger
logger = logging.getLogger(__name__)

# Historical note
# ---------------
# A second orchestrator API (register_orchestrator_poller /
# remove_orchestrator_pollers_by_target, backed by a PollerEntry
# dataclass and _ORCHESTRATOR_POLLER_REGISTRY) used to live here too.
# It was never called from production code — only by its own tests —
# and was removed during the orchestrator consolidation. The "entry"
# API below (register_orchestrator_entry / remove_orchestrator_entries_by_target)
# is the single source of truth now.


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


# Registry for arbitrary orchestrator-managed entries keyed by string identifiers.
# Each key maps to a list of entry dictionaries that may contain runtime metadata.
_ORCH_ENTRIES: Dict[str, List[Dict[str, Any]]] = {}
_ORCH_ENTRIES_LOCK = threading.Lock()


def register_orchestrator_entry(entry_obj: Mapping[str, Any], keys: List[str]) -> None:
    """Register an orchestrator-managed entry under one or more keys.

    ``entry_obj`` must be a mapping (dict-like) with at least a ``poller``
    key. Optional keys ``thread`` and ``queue`` are captured into the
    registry record if present. The production caller is the :agent
    spawn path in terminal_commands.py, which always passes:

        {'poller': <OrchestratorPoller>, 'queue': <Queue>, 'thread': <Thread>?}

    Earlier versions of this helper accepted any object and introspected
    it via getattr() for ``thread``/``poller`` attributes; that branch
    was dead code (no production caller ever used it) and was removed
    during the orchestrator consolidation. Stick with the dict shape.

    The registry stores a flat dict per registration:

        {
            "entry":  <the original entry_obj>,
            "poller": <entry_obj['poller'] if callable, else None>,
            "thread": <entry_obj['thread'] if a Thread, else None>,
        }

    This is the canonical entry shape that ``remove_orchestrator_entries_by_target``
    returns. Trust it from the caller side.

    Thread-safe.

    Args:
        entry_obj: Dict-like with at minimum a ``poller`` key.
        keys: One or more identifiers under which to index the entry.

    Raises:
        ValueError: If ``keys`` is empty.
        TypeError: If ``entry_obj`` is not a Mapping.
    """
    if not keys:
        raise ValueError("keys must contain at least one identifier")
    if not isinstance(entry_obj, Mapping):
        raise TypeError(
            f"entry_obj must be a Mapping (dict-like); got {type(entry_obj).__name__}. "
            "Pass a dict with at least a 'poller' key."
        )

    # Extract optional metadata directly from the mapping — no attribute
    # introspection. If a key is missing or has an unexpected type, it
    # just lands as None in the record.
    poller_candidate = entry_obj.get("poller")
    detected_poller = poller_candidate if callable(poller_candidate) else None
    thread_candidate = entry_obj.get("thread")
    detected_thread = thread_candidate if isinstance(thread_candidate, threading.Thread) else None

    entry_dict: Dict[str, Any] = {
        "entry": entry_obj,
        "thread": detected_thread,
        "poller": detected_poller,
    }

    with _ORCH_ENTRIES_LOCK:
        for k in list(keys):
            _ORCH_ENTRIES.setdefault(k, []).append(entry_dict)
            logger.debug(
                "Registered orchestrator entry %r under key %s. Total entries: %d",
                entry_obj,
                k,
                len(_ORCH_ENTRIES[k]),
            )


def remove_orchestrator_entries_by_target(target_session: str, join_timeout: Optional[float] = 5.0) -> Dict[str, List[Dict[str, Any]]]:
    """Remove and attempt to stop/join orchestrator-managed entries for a session key.

    This function removes and returns the list of entry dictionaries that were
    registered under the specified target_session key. For each removed entry
    the helper will attempt a polite shutdown by calling one of the following
    in this order if present (preference is given to metadata captured under
    the 'poller' key in the stored entry dict):
      - entry_dict['poller'].stop()   # preferred if poller object is present
      - entry.stop()                  # preferred fallback on the raw entry object
      - entry_obj.stop()              # equivalent via attribute access

    After requesting stop it will attempt to join/wait for the entry to exit:
      - entry_dict['poller'].join(timeout)   # if the poller object exposes join
      - entry.join(timeout)                  # if the entry object exposes a join method
      - thread.join(timeout)                 # if a captured thread was stored on registration

    The operation is thread-safe and performs best-effort stopping/joining of
    entries. Exceptions raised by stop/join operations are logged but do not
    prevent other entries from being processed.

    Args:
        target_session: The session key whose entries should be removed.
        join_timeout: Number of seconds to wait for each join call. If None,
            join() will block until the thread/object exits.

    Returns:
        Dict[str, List[Dict[str, Any]]]: A mapping containing the removed
        entries lists keyed by the target_session. If no entries were found
        an empty mapping is returned under the same key.
    """
    with _ORCH_ENTRIES_LOCK:
        removed_entries = _ORCH_ENTRIES.pop(target_session, [])

    if not removed_entries:
        logger.debug("No orchestrator entries found to remove for session %s", target_session)
        return {target_session: []}

    for entry_dict in removed_entries:
        entry_obj = entry_dict.get("entry")
        poller_obj = entry_dict.get("poller")
        # First, attempt to request stop via common method names.
        # Prefer stopping the captured poller object if present.
        stopped = False
        if poller_obj is not None:
            try:
                stop_callable = getattr(poller_obj, "stop", None)
                if callable(stop_callable):
                    try:
                        stop_callable()
                        stopped = True
                        logger.debug("Called stop() on poller metadata %r for session %s", poller_obj, target_session)
                    except Exception:
                        logger.exception("Exception while calling stop() on poller metadata %r for session %s", poller_obj, target_session)
            except Exception:
                logger.exception("Failed to access stop attribute on poller metadata %r for session %s", poller_obj, target_session)

        if not stopped:
            # Fallback to attempting stop() on the raw entry object.
            try:
                stop_callable = getattr(entry_obj, "stop", None)
                if callable(stop_callable):
                    try:
                        stop_callable()
                        logger.debug("Called stop() on orchestrator entry %r for session %s", entry_obj, target_session)
                    except Exception:
                        logger.exception("Exception while calling stop() on orchestrator entry %r for session %s", entry_obj, target_session)
            except Exception:
                # getattr may raise in very unusual objects; log and continue.
                logger.exception("Failed to access stop attribute on orchestrator entry %r for session %s", entry_obj, target_session)

    # Attempt to join/wait for entries to finish. Do this outside the registry lock.
    for entry_dict in removed_entries:
        entry_obj = entry_dict.get("entry")
        poller_obj = entry_dict.get("poller")

        # Prefer joining the poller metadata object if available.
        joined = False
        if poller_obj is not None:
            try:
                join_callable = getattr(poller_obj, "join", None)
                if callable(join_callable):
                    try:
                        if join_timeout is None:
                            join_callable()
                        else:
                            try:
                                join_callable(join_timeout)
                            except TypeError:
                                join_callable()
                        logger.debug("Joined poller metadata %r via its join() for session %s", poller_obj, target_session)
                        joined = True
                    except Exception:
                        logger.exception("Exception while joining poller metadata %r via its join() for session %s", poller_obj, target_session)
            except Exception:
                logger.exception("Failed to access join attribute on poller metadata %r for session %s", poller_obj, target_session)

        if joined:
            continue

        # Next, prefer entry_obj.join if available.
        try:
            join_callable = getattr(entry_obj, "join", None)
            if callable(join_callable):
                try:
                    if join_timeout is None:
                        join_callable()
                    else:
                        # Some join() implementations accept a timeout, others don't.
                        try:
                            join_callable(join_timeout)
                        except TypeError:
                            # Fallback to calling without timeout if timeout not accepted.
                            join_callable()
                    logger.debug("Joined orchestrator entry %r via its join() for session %s", entry_obj, target_session)
                    continue
                except Exception:
                    logger.exception("Exception while joining orchestrator entry %r via its join() for session %s", entry_obj, target_session)
        except Exception:
            logger.exception("Failed to access join attribute on orchestrator entry %r for session %s", entry_obj, target_session)

        # Fall back to any captured thread stored at registration time.
        thread = entry_dict.get("thread")
        if isinstance(thread, threading.Thread):
            try:
                if thread.is_alive():
                    logger.debug("Joining captured thread %r for orchestrator entry %r with timeout=%s", thread, entry_obj, join_timeout)
                    thread.join(timeout=join_timeout)
                    if thread.is_alive():
                        logger.warning(
                            "Captured thread %r for orchestrator entry %r did not stop after %s seconds",
                            thread,
                            entry_obj,
                            join_timeout,
                        )
                    else:
                        logger.debug("Captured thread %r for orchestrator entry %r joined successfully", thread, entry_obj)
            except Exception:
                logger.exception("Exception while joining captured thread %r for orchestrator entry %r", thread, entry_obj)

    logger.debug("Removed %d orchestrator entry(ies) for session %s", len(removed_entries), target_session)
    return {target_session: removed_entries}
