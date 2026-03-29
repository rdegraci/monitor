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
from dataclasses import dataclass, field
from typing import Callable, Any, Dict, List, Optional, Tuple, Mapping

# Set up a module-level logger
logger = logging.getLogger(__name__)

# Dataclass representing a registered poller and its runtime control objects.
@dataclass
class PollerEntry:
    """Container for a registered orchestrator poller.

    Attributes:
        poller: The callable registered as a poller.
        thread: Optional thread object if the poller was started in a thread.
        stop_event: Event used to signal the poller that it should stop.
    """
    poller: Callable[..., Any]
    thread: Optional[threading.Thread] = None
    stop_event: threading.Event = field(default_factory=threading.Event)


# Registry for orchestrator pollers keyed by target identifier.
# Each target maps to a list of PollerEntry objects.
_ORCHESTRATOR_POLLER_REGISTRY: Dict[str, List[PollerEntry]] = {}
_ORCHESTRATOR_POLLER_REGISTRY_LOCK = threading.Lock()


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


def register_orchestrator_poller(
    target: str,
    poller: Callable[..., Any],
    *,
    start_thread: bool = False,
    daemon: bool = True,
    args: Optional[Tuple[Any, ...]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
) -> None:
    """Register a poller callable associated with an orchestrator target.

    The registry stores PollerEntry objects for each target. This function is
    thread-safe. Optionally the poller can be started in its own Thread; in
    that case a threading.Event is created and passed as the first positional
    argument to the poller if the poller accepts it. If the poller does not
    accept the stop event parameter, the implementation falls back to calling
    the poller without the event.

    Args:
        target: Target identifier to associate with the poller.
        poller: Callable to be invoked by orchestrator poller loop or
            scheduling logic.
        start_thread: If True, start the poller inside a new Thread.
        daemon: If starting a thread, set the thread daemon flag to this value.
        args: Additional positional arguments to pass to the poller when the
            thread is started (ignored if start_thread is False).
        kwargs: Additional keyword arguments to pass to the poller when the
            thread is started (ignored if start_thread is False).

    Returns:
        None: The poller is registered in the global registry. If the same
        callable is registered multiple times it will appear multiple times
        in the registry for that target.
    """
    args = tuple(args or ())
    kwargs = dict(kwargs or {})

    entry = PollerEntry(poller=poller)

    if start_thread:
        def _run() -> None:
            """Wrapper that attempts to call the poller with a stop event.

            The wrapper will try to call poller(stop_event, *args, **kwargs)
            first; if that raises a TypeError it will fall back to calling
            poller(*args, **kwargs). Any exception raised by the poller is
            logged and the thread will exit.
            """
            try:
                try:
                    entry.poller(entry.stop_event, *args, **kwargs)
                except TypeError:
                    # Poller did not accept the stop_event argument.
                    entry.poller(*args, **kwargs)
            except Exception:
                logger.exception("Exception in orchestrator poller for target %s", target)
            finally:
                logger.debug("Poller thread for target %s exiting", target)

        thread = threading.Thread(target=_run, daemon=daemon)
        entry.thread = thread
        try:
            thread.start()
            logger.debug("Started poller thread %r for target %s (daemon=%s)", thread, target, daemon)
        except RuntimeError:
            # Thread could not be started (e.g., interpreter shutting down).
            logger.exception("Failed to start poller thread for target %s", target)
            entry.thread = None

    with _ORCHESTRATOR_POLLER_REGISTRY_LOCK:
        _ORCHESTRATOR_POLLER_REGISTRY.setdefault(target, []).append(entry)
        logger.debug(
            "Registered poller %r for target %s. Total pollers: %d",
            poller,
            target,
            len(_ORCHESTRATOR_POLLER_REGISTRY[target]),
        )


def remove_orchestrator_pollers_by_target(target: str, join_timeout: Optional[float] = 5.0) -> List[PollerEntry]:
    """Remove all pollers registered for the given orchestrator target.

    This function removes and returns the list of PollerEntry objects that
    were registered under the specified target. The operation is thread-safe.
    For each removed entry, if a stop_event is present it will be set to
    request polite shutdown. If a thread was associated with the entry and it
    is alive, the function will attempt to join it for up to join_timeout
    seconds per thread.

    Args:
        target: Target identifier whose pollers should be removed.
        join_timeout: Number of seconds to wait for each poller thread to
            join. If None, join() will block until the thread exits.

    Returns:
        List[PollerEntry]: The list of removed poller entries. If no pollers
        were found for the given target an empty list is returned.

    Notes:
        - The function makes a best-effort attempt to stop and join threads.
          If a poller ignores the stop_event or runs non-cooperatively, the
          thread may not exit within join_timeout and will be left running.
        - Callers should design pollers to accept a threading.Event as the
          first argument (and regularly check event.is_set()) when start_thread
          is used so that this removal helper can successfully request shutdown.
    """
    with _ORCHESTRATOR_POLLER_REGISTRY_LOCK:
        entries = _ORCHESTRATOR_POLLER_REGISTRY.pop(target, [])

    if not entries:
        logger.debug("No pollers found to remove for target %s", target)
        return []

    for entry in entries:
        # Signal polite shutdown to the poller
        try:
            entry.stop_event.set()
            logger.debug("Set stop_event for poller %r on target %s", entry.poller, target)
        except Exception:
            logger.exception("Failed to set stop_event for poller %r on target %s", entry.poller, target)

    # Attempt to join threads outside the lock to avoid deadlocks
    for entry in entries:
        thread = entry.thread
        if thread is None:
            continue
        try:
            if thread.is_alive():
                logger.debug("Joining poller thread %r for target %s with timeout=%s", thread, target, join_timeout)
                thread.join(timeout=join_timeout)
                if thread.is_alive():
                    logger.warning(
                        "Poller thread %r for target %s did not stop after %s seconds",
                        thread,
                        target,
                        join_timeout,
                    )
                else:
                    logger.debug("Poller thread %r for target %s joined successfully", thread, target)
        except Exception:
            logger.exception("Exception while joining poller thread %r for target %s", thread, target)

    logger.debug("Removed %d poller(s) for target %s", len(entries), target)
    return entries


# Registry for arbitrary orchestrator-managed entries keyed by string identifiers.
# Each key maps to a list of entry dictionaries that may contain runtime metadata.
_ORCH_ENTRIES: Dict[str, List[Dict[str, Any]]] = {}
_ORCH_ENTRIES_LOCK = threading.Lock()


def register_orchestrator_entry(entry_obj: Any, keys: List[str]) -> None:
    """Register an arbitrary orchestrator-managed entry under one or more keys.

    The registry stores dictionaries per entry that include the original entry
    object and any detected runtime metadata (for example, an associated
    thread if present). This helper is thread-safe.

    The function will detect a few common attributes on the entry object and
    include them in the stored dict:
      - 'thread': If the entry object has a 'thread' attribute that is a
        threading.Thread instance, that thread is captured in the metadata.
      - 'poller': If the entry object is dict-like (Mapping) and contains a
        'poller' key, that value will be captured in the metadata. This is
        useful when orchestrator-managed entries wrap a poller callable and
        expose it under a mapping interface.

    Args:
        entry_obj: The entry object to register. Can be any object that the
            orchestrator manages (e.g., worker objects, connection handles).
        keys: Iterable of string keys under which to register the entry. Each
            key will map to a list of entry dictionaries in the internal
            registry.

    Raises:
        ValueError: If keys is empty.
    """
    if not keys:
        raise ValueError("keys must contain at least one identifier")

    # Normalize keys to a list (caller should pass list[str], but be resilient).
    normalized_keys = list(keys)

    # Collect detected metadata for this entry
    detected_thread = None
    detected_poller = None
    try:
        candidate = getattr(entry_obj, "thread", None)
        if isinstance(candidate, threading.Thread):
            detected_thread = candidate
    except Exception:
        # Don't fail registration just because attribute access raised.
        detected_thread = None

    # Detect dict-like objects that expose a 'poller' or 'thread' key.
    try:
        if isinstance(entry_obj, Mapping):
            # Prefer explicit 'poller' key if present.
            try:
                poller_candidate = entry_obj.get("poller", None)
                if callable(poller_candidate):
                    detected_poller = poller_candidate
            except Exception:
                detected_poller = None

            # If a thread is present in mapping and not already detected, capture it.
            if detected_thread is None:
                try:
                    thread_candidate = entry_obj.get("thread", None)
                    if isinstance(thread_candidate, threading.Thread):
                        detected_thread = thread_candidate
                except Exception:
                    # Ignore mapping access errors.
                    pass
    except Exception:
        # Defensive: if isinstance check or mapping behaviour raises, ignore.
        pass

    entry_dict: Dict[str, Any] = {"entry": entry_obj, "thread": detected_thread, "poller": detected_poller}

    with _ORCH_ENTRIES_LOCK:
        for k in normalized_keys:
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
