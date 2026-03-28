"""LLM-callable wrappers for agent (screen) operations."""

import logging
import uuid
from typing import Any, Dict, Optional

from monitor.lib.screen_handler import get_global_screen_handler
from monitor.lib import subagent_logging

logger = logging.getLogger(__name__)

# Module-level ScreenHandler instance (lazy)
class _LazyScreen:
    """Proxy that lazily retrieves the global ScreenHandler.

    This proxy defers obtaining the real ScreenHandler instance until the
    first attribute access. It is intended to replace an eager import of a
    module-level GLOBAL_SCREEN_HANDLER to avoid expensive initialization at
    import time.

    Attributes:
        _real (Optional[Any]): The actual ScreenHandler instance once loaded.
    """

    def __init__(self) -> None:
        """Initialize the lazy proxy without creating the real handler.

        The real handler will be created on first attribute access.
        """
        # Store the real instance in the instance dict to avoid recursion in
        # __setattr__ and __getattr__.
        self.__dict__["_real"] = None

    def _ensure(self) -> Any:
        """Ensure the real ScreenHandler is available.

        Returns:
            Any: The real ScreenHandler instance obtained from
                get_global_screen_handler().
        """
        real = self.__dict__.get("_real")
        if real is None:
            real = get_global_screen_handler()
            self.__dict__["_real"] = real
        return real

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the real ScreenHandler.

        Args:
            name: The attribute name being accessed.

        Returns:
            Any: The requested attribute from the real ScreenHandler.

        Raises:
            AttributeError: If the underlying handler does not have the attribute.
        """
        real = self._ensure()
        return getattr(real, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """Delegate attribute assignment to the real ScreenHandler.

        Args:
            name: The attribute name to set.
            value: The value to assign to the attribute.
        """
        if name == "_real":
            # Allow setting the internal marker without forcing initialization.
            self.__dict__["_real"] = value
        else:
            real = self._ensure()
            setattr(real, name, value)

    def __repr__(self) -> str:
        """Return a representation indicating whether the real handler is loaded.

        Returns:
            str: A human-readable representation of the proxy.
        """
        real = self.__dict__.get("_real")
        if real is None:
            return "<LazyScreen (uninitialized)>"
        return repr(real)


_SCREEN = _LazyScreen()


def _new_correlation_id() -> str:
    """Generate a short correlation id for audit traces.

    Returns:
        str: A short hex string used to correlate tool calls.
    """
    return uuid.uuid4().hex[:12]


def agent_list(full: bool = False) -> Dict[str, Any]:
    """List active agent (screen) sessions.

    This wrapper exposes the ScreenHandler listing behavior as a structured
    LLM-callable tool. It returns a JSON-serializable dictionary with a
    correlation_id for auditing and the raw sessions data as provided by the
    ScreenHandler. The `full` flag requests additional metadata where the
    underlying handler supports it.

    Args:
        full: If True, include tokens and metadata paths when supported by the handler.

    Returns:
        Dict[str, Any]: A dictionary containing status, correlation_id and sessions.
    """
    cid = _new_correlation_id()
    try:
        try:
            sessions = _SCREEN.list_indexed_sessions(full=full)
        except AttributeError:
            sessions = _SCREEN.list_sessions()
            full = False

        # Return a structured result suitable for LLM consumption
        result = {"status": "ok", "correlation_id": cid, "sessions": sessions, "full": full}
        logger.info("agent_list success: cid=%s, count=%d", cid, len(sessions) if sessions else 0)
        return result
    except Exception as exc:
        logger.exception("agent_list failed: %s", exc)
        return {"status": "error", "correlation_id": cid, "message": str(exc)}


def agent_logfile(index: int) -> Dict[str, Any]:
    """Locate the logfile for a given agent (screen) session by numeric index.

    This function accepts a numeric index and resolves it to a session name using
    ScreenHandler.get_session_by_index. The resolved value may be a string,
    dict, tuple, or object; this function attempts to extract a meaningful
    session name robustly from those types. It then uses
    monitor.lib.subagent_logging.find_logfile_for_session_name to locate the
    associated logfile.

    Args:
        index: The numeric index referencing a session.

    Returns:
        Dict[str, Any]: A dictionary containing status, correlation_id, the
            provided index, the resolved session name and the logfile path
            (or an error message on failure).
    """
    cid = _new_correlation_id()

    # Input validation: require an int index
    if not isinstance(index, int):
        msg = "index must be an int"
        logger.error("agent_logfile validation failed: cid=%s, index=%r, msg=%s", cid, index, msg)
        return {"status": "error", "correlation_id": cid, "index": index, "message": msg}

    try:
        # Resolve index to session using the handler
        try:
            resolved = _SCREEN.get_session_by_index(index)
        except AttributeError:
            # Handler does not support index lookup; surface a clear error.
            raise RuntimeError("ScreenHandler.get_session_by_index is not available")
        except Exception:
            # Any other error during resolution should be raised to the outer handler.
            raise

        # Robustly extract a session name from various possible return types.
        session_name: Optional[str] = None

        # If it's a simple string, use it directly.
        if isinstance(resolved, str):
            session_name = resolved
        # If it's a dict, try common keys then any string value.
        elif isinstance(resolved, dict):
            for key in ("name", "session", "session_name", "id", "title"):
                if key in resolved and isinstance(resolved[key], str) and resolved[key]:
                    session_name = resolved[key]
                    break
            if not session_name:
                for v in resolved.values():
                    if isinstance(v, str) and v:
                        session_name = v
                        break
        # If it's a list/tuple, inspect the first element.
        elif isinstance(resolved, (list, tuple)):
            if resolved:
                first = resolved[0]
                if isinstance(first, str):
                    session_name = first
                elif isinstance(first, dict):
                    for key in ("name", "session", "session_name", "id", "title"):
                        if key in first and isinstance(first[key], str) and first[key]:
                            session_name = first[key]
                            break
                else:
                    session_name = str(first) if first is not None else ""
        # Otherwise, try common attributes on objects or fall back to str().
        else:
            for attr in ("name", "session", "session_name", "id", "title"):
                if hasattr(resolved, attr):
                    val = getattr(resolved, attr)
                    if isinstance(val, str) and val:
                        session_name = val
                        break
            if not session_name:
                # As a last resort use the string representation.
                session_name = str(resolved) if resolved is not None else ""

        if not session_name:
            raise RuntimeError("Could not resolve session name from get_session_by_index result")

        # Use the subagent_logging helper to find the logfile for the resolved session name.
        try:
            logfile = subagent_logging.find_logfile_for_session_name(session_name)
        except AttributeError:
            # subagent_logging does not expose the helper we expect.
            raise RuntimeError("subagent_logging.find_logfile_for_session_name is not available")
        except Exception:
            # Re-raise any other exception to be handled uniformly below.
            raise

        result = {
            "status": "ok",
            "correlation_id": cid,
            "index": index,
            "session": session_name,
            "logfile": logfile,
        }
        logger.info(
            "agent_logfile success: cid=%s, index=%s, session=%s, logfile=%s",
            cid,
            index,
            session_name,
            logfile,
        )
        return result
    except Exception as exc:
        logger.exception("agent_logfile failed: %s", exc)
        return {"status": "error", "correlation_id": cid, "index": index, "message": str(exc)}


def agent_kill(index: int) -> Dict[str, Any]:
    """Kill an agent (screen) session identified by numeric index.

    This function validates that the provided index is an int, resolves it to a
    session name via ScreenHandler.get_session_by_index, and then requests the
    handler to kill the resolved session by calling ScreenHandler.kill_session.
    The function returns a structured dictionary suitable for LLM consumption
    with a correlation id for auditing.

    Args:
        index: The numeric index referencing a session to kill.

    Returns:
        Dict[str, Any]: A dictionary containing status, correlation_id, the
            provided index, the resolved session name, and a 'killed' boolean
            indicating whether the kill operation reported success. On error,
            returns an error message instead.
    """
    cid = _new_correlation_id()

    # Input validation: require an int index
    if not isinstance(index, int):
        msg = "index must be an int"
        logger.error("agent_kill validation failed: cid=%s, index=%r, msg=%s", cid, index, msg)
        return {"status": "error", "correlation_id": cid, "index": index, "message": msg}

    try:
        # Resolve index to session using the handler
        try:
            resolved = _SCREEN.get_session_by_index(index)
        except AttributeError:
            # Handler does not support index lookup; surface a clear error.
            raise RuntimeError("ScreenHandler.get_session_by_index is not available")
        except Exception:
            # Any other error during resolution should be raised to the outer handler.
            raise

        # Robustly extract a session name from various possible return types.
        session_name: Optional[str] = None

        # If it's a simple string, use it directly.
        if isinstance(resolved, str):
            session_name = resolved
        # If it's a dict, try common keys then any string value.
        elif isinstance(resolved, dict):
            for key in ("name", "session", "session_name", "id", "title"):
                if key in resolved and isinstance(resolved[key], str) and resolved[key]:
                    session_name = resolved[key]
                    break
            if not session_name:
                for v in resolved.values():
                    if isinstance(v, str) and v:
                        session_name = v
                        break
        # If it's a list/tuple, inspect the first element.
        elif isinstance(resolved, (list, tuple)):
            if resolved:
                first = resolved[0]
                if isinstance(first, str):
                    session_name = first
                elif isinstance(first, dict):
                    for key in ("name", "session", "session_name", "id", "title"):
                        if key in first and isinstance(first[key], str) and first[key]:
                            session_name = first[key]
                            break
                else:
                    session_name = str(first) if first is not None else ""
        # Otherwise, try common attributes on objects or fall back to str().
        else:
            for attr in ("name", "session", "session_name", "id", "title"):
                if hasattr(resolved, attr):
                    val = getattr(resolved, attr)
                    if isinstance(val, str) and val:
                        session_name = val
                        break
            if not session_name:
                # As a last resort use the string representation.
                session_name = str(resolved) if resolved is not None else ""

        if not session_name:
            raise RuntimeError("Could not resolve session name from get_session_by_index result")

        # Request the handler to kill the session.
        try:
            try:
                killed = _SCREEN.kill_session(session_name)
            except AttributeError:
                # Handler does not expose a kill method we expect.
                raise RuntimeError("ScreenHandler.kill_session is not available")
            except Exception:
                # Re-raise to be handled uniformly below.
                raise
        except Exception:
            # Ensure killed is set for the result in case of unexpected flows.
            raise

        # Normalize killed to a boolean for structured return.
        killed_bool = bool(killed)

        result = {
            "status": "ok",
            "correlation_id": cid,
            "index": index,
            "session": session_name,
            "killed": killed_bool,
        }
        logger.info(
            "agent_kill success: cid=%s, index=%s, session=%s, killed=%s",
            cid,
            index,
            session_name,
            killed_bool,
        )
        return result
    except Exception as exc:
        logger.exception("agent_kill failed: %s", exc)
        return {"status": "error", "correlation_id": cid, "index": index, "message": str(exc)}


def agent_send(index: int, text: str) -> Dict[str, Any]:
    """Send text to an agent (screen) session identified by numeric index.

    This function validates the provided index and text, resolves the index to
    a session name via ScreenHandler.get_session_by_index, and then requests the
    handler to send the provided text to the resolved session by calling
    ScreenHandler.send_to_session. The function returns a structured dictionary
    suitable for LLM consumption with a correlation id for auditing. The
    returned 'text_preview' contains the first 200 characters of the sent text.

    Args:
        index: The numeric index referencing a session to send text to.
        text: The text to send to the session.

    Returns:
        Dict[str, Any]: A dictionary containing status, correlation_id, the
            provided index, the resolved session name, a 'sent' boolean
            indicating whether the send operation reported success, and a
            'text_preview' with the first 200 characters of the provided text.
            On error, returns an error message instead.
    """
    cid = _new_correlation_id()

    # Input validation: require an int index and str text
    if not isinstance(index, int):
        msg = "index must be an int"
        logger.error("agent_send validation failed: cid=%s, index=%r, msg=%s", cid, index, msg)
        return {"status": "error", "correlation_id": cid, "index": index, "message": msg}
    if not isinstance(text, str):
        msg = "text must be a str"
        logger.error("agent_send validation failed: cid=%s, index=%r, msg=%s", cid, index, msg)
        return {"status": "error", "correlation_id": cid, "index": index, "message": msg}

    try:
        # Resolve index to session using the handler
        try:
            resolved = _SCREEN.get_session_by_index(index)
        except AttributeError:
            # Handler does not support index lookup; surface a clear error.
            raise RuntimeError("ScreenHandler.get_session_by_index is not available")
        except Exception:
            # Any other error during resolution should be raised to the outer handler.
            raise

        # Robustly extract a session name from various possible return types.
        session_name: Optional[str] = None

        # If it's a simple string, use it directly.
        if isinstance(resolved, str):
            session_name = resolved
        # If it's a dict, try common keys then any string value.
        elif isinstance(resolved, dict):
            for key in ("name", "session", "session_name", "id", "title"):
                if key in resolved and isinstance(resolved[key], str) and resolved[key]:
                    session_name = resolved[key]
                    break
            if not session_name:
                for v in resolved.values():
                    if isinstance(v, str) and v:
                        session_name = v
                        break
        # If it's a list/tuple, inspect the first element.
        elif isinstance(resolved, (list, tuple)):
            if resolved:
                first = resolved[0]
                if isinstance(first, str):
                    session_name = first
                elif isinstance(first, dict):
                    for key in ("name", "session", "session_name", "id", "title"):
                        if key in first and isinstance(first[key], str) and first[key]:
                            session_name = first[key]
                            break
                else:
                    session_name = str(first) if first is not None else ""
        # Otherwise, try common attributes on objects or fall back to str().
        else:
            for attr in ("name", "session", "session_name", "id", "title"):
                if hasattr(resolved, attr):
                    val = getattr(resolved, attr)
                    if isinstance(val, str) and val:
                        session_name = val
                        break
            if not session_name:
                # As a last resort use the string representation.
                session_name = str(resolved) if resolved is not None else ""

        if not session_name:
            raise RuntimeError("Could not resolve session name from get_session_by_index result")

        # Request the handler to send the text to the session.
        try:
            try:
                sent = _SCREEN.send_to_session(session_name, text)
            except AttributeError:
                # Handler does not expose a send method we expect.
                raise RuntimeError("ScreenHandler.send_to_session is not available")
            except Exception:
                # Re-raise to be handled uniformly below.
                raise
        except Exception:
            # Ensure sent is set for the result in case of unexpected flows.
            raise

        # Normalize sent to a boolean for structured return.
        sent_bool = bool(sent)

        # Prepare a preview of the text for the structured response.
        text_preview = text[:200] if text is not None else ""

        result = {
            "status": "ok",
            "correlation_id": cid,
            "index": index,
            "session": session_name,
            "sent": sent_bool,
            "text_preview": text_preview,
        }
        logger.info(
            "agent_send success: cid=%s, index=%s, session=%s, sent=%s, preview_length=%d",
            cid,
            index,
            session_name,
            sent_bool,
            len(text_preview),
        )
        return result
    except Exception as exc:
        logger.exception("agent_send failed: %s", exc)
        return {"status": "error", "correlation_id": cid, "index": index, "message": str(exc)}
