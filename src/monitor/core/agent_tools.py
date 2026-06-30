"""LLM-callable wrappers for agent (screen) operations."""

import logging
import uuid
import os
from typing import Any, Dict, Optional

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
            # Import the potentially expensive get_global_screen_handler
            # lazily to avoid module import-time overhead and side effects.
            from monitor.lib.screen_handler import get_global_screen_handler

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


def _orchestration_enabled() -> bool:
    """Check whether agent orchestration is enabled via configuration.

    The agent orchestration feature is gated by the configuration key
    MONITOR_ENABLE_AGENT_ORCHESTRATION. This function first consults the
    environment variable MONITOR_ENABLE_AGENT_ORCHESTRATION; if the variable
    is present it is interpreted (strings like '1', 'true', 'yes', 'on' are
    treated as truthy). If the environment variable is not set, the function
    falls back to lazily reading monitor.config.MONITOR_ENABLE_AGENT_ORCHESTRATION
    (either a module attribute or via config.get()).

    Any unexpected error during detection results in orchestration being
    considered disabled (conservative default).
    Returns:
        bool: True if orchestration is enabled, False otherwise.
    """
    try:
        # First, check for an explicit environment override.
        try:
            env_val = os.getenv("MONITOR_ENABLE_AGENT_ORCHESTRATION")
        except Exception:
            env_val = None

        if env_val is not None:
            # Interpret strings like '1', 'true', 'yes', 'on' as truthy; otherwise use Python truthiness.
            if isinstance(env_val, str):
                return env_val == "1" or env_val.lower() in ("true", "yes", "y", "on")
            return bool(env_val)

        # Lazily import the configuration to avoid circular import at module import time.
        try:
            from monitor import config
        except Exception:
            config = None  # type: ignore[assignment]

        # Prefer a direct attribute on the config module, fall back to a get method if present.
        val = getattr(config, "MONITOR_ENABLE_AGENT_ORCHESTRATION", None) if config is not None else None
        if val is None:
            get = getattr(config, "get", None) if config is not None else None
            if callable(get):
                try:
                    val = get("MONITOR_ENABLE_AGENT_ORCHESTRATION")
                except Exception:
                    val = None

        # Interpret strings like '1', 'true', 'yes', 'on' as truthy; otherwise use Python truthiness.
        if isinstance(val, str):
            return val == "1" or val.lower() in ("true", "yes", "y", "on")
        return bool(val)
    except Exception:
        # On any unexpected error, be conservative and disable orchestration.
        return False


def _agent_caps() -> "tuple[int, int]":
    """Return (max_breadth, max_total) spawn caps (Phase 8c).

    max_breadth = max concurrently-running sub-agents; max_total = max spawned
    per orchestrator session (runaway backstop). Env overrides config; both fall
    back to **maximally conservative SAFE defaults** — breadth 1 AND total 1, so
    at most ONE sub-agent is ever spawned per session until the user deliberately
    raises the limits. A value of 0 disables that cap. Raise via
    `MONITOR_AGENT_MAX_BREADTH` / `MONITOR_AGENT_MAX_TOTAL` (env or config) once
    the workflow is trusted.
    """
    def _read(env_key: str, default: int) -> int:
        val = os.getenv(env_key)
        if val is None:
            try:
                from monitor import config
                val = getattr(config, env_key, None)
            except Exception:
                val = None
        if val is None:
            return default
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    return _read("MONITOR_AGENT_MAX_BREADTH", 1), _read("MONITOR_AGENT_MAX_TOTAL", 1)


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


def agent_create(
    prompt: str,
    persistent: bool = False,
    write_access: bool = False,
    write_scope: str = "",
) -> Dict[str, Any]:
    """Create an interactive subagent (screen) session.

    This wrapper requests the ScreenHandler to create an interactive subagent
    using the provided prompt. It returns a structured result suitable for
    LLM consumption with a correlation id for auditing.

    The returned structure attempts to normalize the handler's response into
    a session name, a metadata path and a logfile path where available.

    Args:
        prompt: The prompt to use when creating the interactive subagent.
        persistent: If False (default), the sub-agent is ONE-SHOT — it exits
            after reporting its result, reaping itself. If True, it stays alive
            for agent_send follow-ups and must be agent_kill-ed when done.
        write_access: If True, grant this specific sub-agent delegated write
            authority for the task.
        write_scope: Optional newline-delimited path scope for delegated
            writes. Empty means no path restriction beyond the write grant.

    Returns:
        Dict[str, Any]: A dictionary containing status, correlation_id, and on
            success the keys 'session_name', 'meta_path', and 'log_path'. On
            failure, returns status 'error' with a message.
    """
    cid = _new_correlation_id()

    # Orchestration gating: refuse to create sub-agents unless explicitly enabled.
    if not _orchestration_enabled():
        msg = "Agent orchestration is disabled. Set MONITOR_ENABLE_AGENT_ORCHESTRATION=1 to enable."
        logger.warning("agent_create orchestration disabled: cid=%s, prompt=%r", cid, prompt)
        return {"status": "error", "correlation_id": cid, "message": msg}

    # Input validation: require a str prompt
    if not isinstance(prompt, str):
        msg = "prompt must be a str"
        logger.error("agent_create validation failed: cid=%s, prompt=%r, msg=%s", cid, prompt, msg)
        return {"status": "error", "correlation_id": cid, "message": msg}
    if not isinstance(write_access, bool):
        msg = "write_access must be a bool"
        logger.error("agent_create validation failed: cid=%s, write_access=%r", cid, write_access)
        return {"status": "error", "correlation_id": cid, "message": msg}
    if not isinstance(write_scope, str):
        msg = "write_scope must be a str"
        logger.error("agent_create validation failed: cid=%s, write_scope=%r", cid, write_scope)
        return {"status": "error", "correlation_id": cid, "message": msg}
    if write_scope.strip() and not write_access:
        msg = "write_scope requires write_access=true"
        logger.error(
            "agent_create validation failed: cid=%s, write_access=%r, write_scope=%r",
            cid,
            write_access,
            write_scope,
        )
        return {"status": "error", "correlation_id": cid, "message": msg}

    # Breadth / total caps (Phase 8c): bound concurrent and lifetime fan-out so
    # "create subagents as necessary" can't become a cost incident.
    try:
        from monitor.lib import agent_orchestrator
        max_breadth, max_total = _agent_caps()
        ok_spawn, reason = agent_orchestrator.can_spawn(max_breadth, max_total)
        if not ok_spawn:
            msg = (
                f"Agent not created: {reason}. Wait for running agents to finish "
                f"(use agent_gather), or raise MONITOR_AGENT_MAX_BREADTH / "
                f"MONITOR_AGENT_MAX_TOTAL."
            )
            logger.warning("agent_create capped: cid=%s, reason=%s", cid, reason)
            return {"status": "error", "correlation_id": cid, "message": msg}
    except Exception:
        logger.debug("agent_create: cap check unavailable; proceeding", exc_info=True)

    try:
        # Request creation from the handler, handling the blocked case explicitly.
        try:
            info = _SCREEN.create_interactive_subagent(
                prompt,
                persistent=persistent,
                write_access=write_access,
                write_scope=write_scope,
            )
        except Exception as exc:
            # Import SubagentCreationBlocked lazily; handle the blocked case if available.
            try:
                from monitor.lib.screen_handler import SubagentCreationBlocked  # type: ignore
            except Exception:
                SubagentCreationBlocked = None  # type: ignore

            if SubagentCreationBlocked is not None and isinstance(exc, SubagentCreationBlocked):
                # Creation was blocked; return an error result but do not raise.
                logger.warning("agent_create blocked: cid=%s, prompt=%r, exc=%s", cid, prompt, exc)
                return {"status": "error", "correlation_id": cid, "message": str(exc)}
            if isinstance(exc, AttributeError):
                # Handler does not expose the expected API.
                raise RuntimeError("ScreenHandler.create_interactive_subagent is not available")
            # Propagate other exceptions to be handled uniformly below.
            raise

        # Normalize the returned info into session_name, meta_path, log_path.
        session_name: Optional[str] = None
        meta_path: Optional[str] = None
        log_path: Optional[str] = None

        # If it's a simple string, treat it as the session name.
        if isinstance(info, str):
            session_name = info
        # If it's a dict, extract common keys.
        elif isinstance(info, dict):
            for key in ("session_name", "name", "session", "id", "title"):
                if key in info and isinstance(info[key], str) and info[key]:
                    session_name = info[key]
                    break
            for key in ("meta_path", "meta", "meta_file", "meta_filepath", "metadata_path"):
                if key in info and isinstance(info[key], str) and info[key]:
                    meta_path = info[key]
                    break
            for key in ("log_path", "logfile", "log_file", "logpath", "logfile_path"):
                if key in info and isinstance(info[key], str) and info[key]:
                    log_path = info[key]
                    break
        # If it's a list/tuple, inspect positional elements.
        elif isinstance(info, (list, tuple)):
            if info:
                first = info[0]
                if isinstance(first, str):
                    session_name = first
                elif isinstance(first, dict):
                    for key in ("session_name", "name", "session", "id", "title"):
                        if key in first and isinstance(first[key], str) and first[key]:
                            session_name = first[key]
                            break
                else:
                    session_name = str(first) if first is not None else ""
                if len(info) > 1 and isinstance(info[1], str):
                    meta_path = info[1]
                if len(info) > 2 and isinstance(info[2], str):
                    log_path = info[2]
        # Otherwise, try common attributes on objects, then fall back to str().
        else:
            for attr in ("session_name", "name", "session", "id", "title"):
                if hasattr(info, attr):
                    val = getattr(info, attr)
                    if isinstance(val, str) and val:
                        session_name = val
                        break
            if session_name is None:
                for attr in ("meta_path", "meta", "meta_file", "meta_filepath", "metadata_path"):
                    if hasattr(info, attr):
                        val = getattr(info, attr)
                        if isinstance(val, str) and val:
                            meta_path = val
                            break
            if log_path is None:
                for attr in ("log_path", "logfile", "log_file", "logpath", "logfile_path"):
                    if hasattr(info, attr):
                        val = getattr(info, attr)
                        if isinstance(val, str) and val:
                            log_path = val
                            break
            if not session_name:
                session_name = str(info) if info is not None else ""

        if not session_name:
            raise RuntimeError("Could not resolve session name from create_interactive_subagent result")

        # Record the spawn for the breadth/total caps (Phase 8c). session_name is
        # the agent_id the child reports under (MONITOR_AGENT_ID), so this also
        # pre-registers it for heartbeat-lapse reaping if it never connects.
        try:
            agent_orchestrator.note_spawn(session_name)
            agent_orchestrator.note_spawn_lifecycle(session_name, persistent=persistent)
        except Exception:
            logger.debug("agent_create: note_spawn failed", exc_info=True)

        result = {
            "status": "ok",
            "correlation_id": cid,
            "session_name": session_name,
            "meta_path": meta_path,
            "log_path": log_path,
            "persistent": bool(persistent),
        }
        print(
            f"Started {'persistent' if persistent else 'one-shot'} sub-agent "
            f"'{session_name}'."
        )
        prompt_preview = prompt if len(prompt) <= 500 else f"{prompt[:500]}..."
        print(f"Prompt: {prompt_preview}")
        logger.info(
            "agent_create success: cid=%s, session=%s, meta=%s, log=%s",
            cid,
            session_name,
            meta_path,
            log_path,
        )
        return result
    except Exception as exc:
        logger.exception("agent_create failed: %s", exc)
        return {"status": "error", "correlation_id": cid, "message": str(exc)}


def _normalize_session_name(resolved) -> Optional[str]:
    """Extract a session_name string from a get_session_by_index result, which
    may be a str / dict / list / object."""
    if isinstance(resolved, str):
        return resolved or None
    if isinstance(resolved, dict):
        for key in ("session_name", "name", "session", "id", "title"):
            v = resolved.get(key)
            if isinstance(v, str) and v:
                return v
        for v in resolved.values():
            if isinstance(v, str) and v:
                return v
        return None
    if isinstance(resolved, (list, tuple)):
        return _normalize_session_name(resolved[0]) if resolved else None
    for attr in ("session_name", "name", "session", "id", "title"):
        v = getattr(resolved, attr, None)
        if isinstance(v, str) and v:
            return v
    return str(resolved) if resolved is not None else None


def _resolve_agent_ref(ref) -> Optional[str]:
    """Resolve an agent reference to a session_name.

    ``ref`` is normally the ``session_name`` returned by ``agent_create`` (the
    only identifier the orchestrator LLM actually has); a 1-based list index
    (as shown by ``:agent list``) is also accepted. Returns None if it can't be
    resolved to a known session.
    """
    s = str(ref).strip()
    if not s:
        return None
    # Primary path: a known session_name (what agent_create hands the model).
    try:
        for entry in _SCREEN.load_sessions_index():
            if entry.get("session_name") == s:
                return s
    except Exception:
        pass
    # Fallback: a 1-based index into the sessions list.
    if s.isdigit():
        try:
            return _normalize_session_name(_SCREEN.get_session_by_index(int(s)))
        except Exception:
            return None
    return None


def _session_lifecycle_metadata(session_name: str) -> Dict[str, Any]:
    try:
        meta = _SCREEN.session_metadata(session_name)
    except AttributeError:
        meta = None
    return meta if isinstance(meta, dict) else {}


def _agent_send_block_reason(session_name: str) -> Optional[str]:
    from monitor.lib import agent_orchestrator as orch

    rec = orch.agent_record(session_name) or {}
    meta = _session_lifecycle_metadata(session_name)

    persistent = meta.get("persistent")
    if persistent is None and meta:
        persistent = not bool(meta.get("one_shot"))
    if persistent is False:
        return (
            "Agent session does not accept follow-ups: it was created as one-shot. "
            "Create it with persistent=true to use agent_send."
        )
    if rec.get("dirty"):
        return "Agent session is no longer usable: it crashed or disconnected."
    if rec.get("_reaped"):
        return "Agent session is no longer usable: it was idle-reaped after completion."
    if rec.get("error"):
        return "Agent session is no longer usable: it reported an error."
    if rec and not rec.get("terminal"):
        return "Agent session is still busy. Wait for it to finish before sending a follow-up."
    return None


def agent_logfile(session) -> Dict[str, Any]:
    """Locate the logfile for an agent (screen) session.

    Args:
        session: the ``session_name`` returned by ``agent_create`` (a 1-based
            index from ``:agent list`` is also accepted).

    Returns:
        Dict[str, Any]: status, correlation_id, the resolved session name and
            the logfile path (or an error message on failure).
    """
    cid = _new_correlation_id()
    if not isinstance(session, (str, int)) or (isinstance(session, str) and not session.strip()):
        msg = "session must be a session_name string (or a 1-based index)"
        logger.error("agent_logfile validation failed: cid=%s, session=%r", cid, session)
        return {"status": "error", "correlation_id": cid, "session": session, "message": msg}

    try:
        session_name = _resolve_agent_ref(session)
        if not session_name:
            return {"status": "error", "correlation_id": cid, "session": session,
                    "message": f"No such agent session: {session!r}"}
        try:
            logfile = subagent_logging.find_logfile_for_session_name(session_name)
        except AttributeError:
            raise RuntimeError("subagent_logging.find_logfile_for_session_name is not available")

        result = {
            "status": "ok",
            "correlation_id": cid,
            "session": session_name,
            "logfile": logfile,
        }
        logger.info("agent_logfile success: cid=%s, session=%s, logfile=%s", cid, session_name, logfile)
        return result
    except Exception as exc:
        logger.exception("agent_logfile failed: %s", exc)
        return {"status": "error", "correlation_id": cid, "session": session, "message": str(exc)}


def agent_kill(session) -> Dict[str, Any]:
    """Kill an agent (screen) session.

    Args:
        session: the ``session_name`` returned by ``agent_create`` (a 1-based
            index from ``:agent list`` is also accepted).

    Returns:
        Dict[str, Any]: status, correlation_id, resolved session name, and a
            'killed' boolean (or an error message on failure).
    """
    cid = _new_correlation_id()
    if not isinstance(session, (str, int)) or (isinstance(session, str) and not session.strip()):
        msg = "session must be a session_name string (or a 1-based index)"
        logger.error("agent_kill validation failed: cid=%s, session=%r", cid, session)
        return {"status": "error", "correlation_id": cid, "session": session, "message": msg}

    try:
        session_name = _resolve_agent_ref(session)
        if not session_name:
            return {"status": "error", "correlation_id": cid, "session": session,
                    "message": f"No such agent session: {session!r}"}
        try:
            killed = _SCREEN.kill_session(session_name)
        except AttributeError:
            raise RuntimeError("ScreenHandler.kill_session is not available")

        killed_bool = bool(killed)
        result = {
            "status": "ok",
            "correlation_id": cid,
            "session": session_name,
            "killed": killed_bool,
        }
        logger.info("agent_kill success: cid=%s, session=%s, killed=%s", cid, session_name, killed_bool)
        return result
    except Exception as exc:
        logger.exception("agent_kill failed: %s", exc)
        return {"status": "error", "correlation_id": cid, "session": session, "message": str(exc)}


def agent_send(session, text: str) -> Dict[str, Any]:
    """Send text to a (persistent) agent session — a follow-up prompt.

    Args:
        session: the ``session_name`` returned by ``agent_create`` (a 1-based
            index from ``:agent list`` is also accepted).
        text: the text to send to the session.

    Returns:
        Dict[str, Any]: status, correlation_id, resolved session name, a 'sent'
            boolean, and a 'text_preview' (first 200 chars). Error on failure.
    """
    cid = _new_correlation_id()

    # Orchestration gating: refuse to send to sub-agents unless explicitly enabled.
    if not _orchestration_enabled():
        msg = "Agent orchestration is disabled. Set MONITOR_ENABLE_AGENT_ORCHESTRATION=1 to enable."
        logger.warning("agent_send orchestration disabled: cid=%s, session=%r", cid, session)
        return {"status": "error", "correlation_id": cid, "session": session, "message": msg}

    if not isinstance(session, (str, int)) or (isinstance(session, str) and not session.strip()):
        msg = "session must be a session_name string (or a 1-based index)"
        logger.error("agent_send validation failed: cid=%s, session=%r", cid, session)
        return {"status": "error", "correlation_id": cid, "session": session, "message": msg}
    if not isinstance(text, str):
        msg = "text must be a str"
        logger.error("agent_send validation failed: cid=%s, session=%r, msg=%s", cid, session, msg)
        return {"status": "error", "correlation_id": cid, "session": session, "message": msg}

    try:
        session_name = _resolve_agent_ref(session)
        if not session_name:
            return {"status": "error", "correlation_id": cid, "session": session,
                    "message": f"No such agent session: {session!r}"}
        reason = _agent_send_block_reason(session_name)
        if reason:
            return {
                "status": "error",
                "correlation_id": cid,
                "session": session_name,
                "message": reason,
            }
        try:
            sent = _SCREEN.send_to_session(session_name, text)
        except AttributeError:
            raise RuntimeError("ScreenHandler.send_to_session is not available")

        sent_bool = bool(sent)
        if sent_bool:
            try:
                from monitor.lib import agent_orchestrator
                agent_orchestrator.note_followup_sent(session_name)
            except Exception:
                logger.debug("agent_send: note_followup_sent failed", exc_info=True)
        text_preview = text[:200] if text is not None else ""
        result = {
            "status": "ok",
            "correlation_id": cid,
            "session": session_name,
            "sent": sent_bool,
            "text_preview": text_preview,
        }
        logger.info(
            "agent_send success: cid=%s, session=%s, sent=%s, preview_length=%d",
            cid, session_name, sent_bool, len(text_preview),
        )
        return result
    except Exception as exc:
        logger.exception("agent_send failed: %s", exc)
        return {"status": "error", "correlation_id": cid, "session": session, "message": str(exc)}


def agent_gather(agent_ids: Any, timeout: float = 120.0, poll_interval: float = 0.25) -> Dict[str, Any]:
    """Block until the listed sub-agents finish, then return their results.

    The orchestration primitive that lets an LLM fan out work and aggregate it
    *in-context* (PLAN Phase 8a): fire N ``agent_create`` calls, then pass their
    returned ``session_name`` values here. This blocks until every listed agent
    reaches a terminal state (reported a result/error or exited cleanly) or
    crashes (dirty disconnect), or until ``timeout`` seconds elapse.

    Partial-failure honesty (8d): every requested id lands in exactly one of
    ``ok`` / ``failed`` / ``pending`` — a crashed, errored, or never-connected
    agent is reported, never silently dropped.

    Args:
        agent_ids: a session_name (str) or list of them (as returned by
            ``agent_create``).
        timeout: maximum seconds to wait for all agents to finish.
        poll_interval: how often to poll the orchestrator registry.

    Returns:
        Dict with status, correlation_id, requested count, and the buckets
        ``ok`` ([{id, result}]), ``failed`` ([{id, reason}]), ``pending``
        ([id...]), plus ``timed_out`` (bool).
    """
    cid = _new_correlation_id()

    # Orchestration gating: same master switch as agent_create/agent_send.
    if not _orchestration_enabled():
        msg = "Agent orchestration is disabled. Set MONITOR_ENABLE_AGENT_ORCHESTRATION=1 to enable."
        logger.warning("agent_gather orchestration disabled: cid=%s", cid)
        return {"status": "error", "correlation_id": cid, "message": msg}

    # Normalize agent_ids to a list of strings.
    if isinstance(agent_ids, str):
        ids = [agent_ids]
    elif isinstance(agent_ids, (list, tuple)):
        ids = [str(a) for a in agent_ids]
    else:
        return {"status": "error", "correlation_id": cid,
                "message": "agent_ids must be a string or a list of strings"}
    if not ids:
        return {"status": "error", "correlation_id": cid, "message": "agent_ids is empty"}

    try:
        timeout = max(0.0, float(timeout))
    except (TypeError, ValueError):
        timeout = 120.0

    import time
    from monitor.lib import agent_orchestrator as orch

    def _resolved(aid: str) -> bool:
        rec = orch.agent_record(aid)
        if rec is None:
            return False  # hasn't connected yet
        return bool(rec.get("terminal") or rec.get("dirty"))

    deadline = time.monotonic() + timeout
    while True:
        if all(_resolved(a) for a in ids):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_interval)

    ok, failed, pending = [], [], []
    for aid in ids:
        rec = orch.agent_record(aid)
        if rec is None:
            failed.append({"id": aid, "reason": "no such agent (never connected to orchestrator)"})
        elif rec.get("error"):
            failed.append({"id": aid, "reason": rec["error"].get("message", "reported error")})
        elif rec.get("dirty"):
            failed.append({"id": aid, "reason": "dirty disconnect (agent crashed before reporting a result)"})
        elif rec.get("results"):
            ok.append({"id": aid, "result": rec["results"][-1]})
        elif rec.get("terminal"):
            # Exited cleanly but never sent a structured result frame.
            ok.append({"id": aid, "result": {
                "ok": True,
                "summary": rec.get("status") or "completed (no result frame)",
                "no_result_frame": True,
            }})
        else:
            pending.append(aid)  # still running at timeout

    result = {
        "status": "ok",
        "correlation_id": cid,
        "requested": len(ids),
        "ok": ok,
        "failed": failed,
        "pending": pending,
        "timed_out": bool(pending),
    }
    logger.info(
        "agent_gather: cid=%s requested=%d ok=%d failed=%d pending=%d",
        cid, len(ids), len(ok), len(failed), len(pending),
    )
    return result
