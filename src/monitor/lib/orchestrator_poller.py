"""Orchestrator-side poller for monitoring sub-agent status.

This module provides OrchestratorPoller, a small background watcher that polls
an agent's Unix Domain Socket (MONITOR_STATUS_SOCKET) for status JSON and
publishes state-change events to a threadsafe queue or a callback. It is
intended to be used by the synchronous main chat loop: start a poller for each
created agent and check its queue at natural breakpoints to learn about
completion without blocking the chat loop.
"""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
from queue import Queue, Empty
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class OrchestratorPoller:
    """Background poller for a single sub-agent status socket.

    The poller connects to a Unix Domain Socket at `socket_path` repeatedly,
    reads a single JSON response (the child's status snapshot) and notifies
    callers when the observed payload changes. Notifications are delivered
    either via an optional `on_update` callback (called from the watcher
    thread) or by enqueuing events into a threadsafe Queue supplied by the
    caller.

    Args:
        session_name: The short session identifier for the agent (for logging).
        socket_path: Path to the agent's MONITOR_STATUS_SOCKET (UDS path).
        queue: Optional Queue to which JSON payload dicts will be posted on change.
        on_update: Optional callable(payload: Dict[str, Any]) invoked on change.
        poll_interval: Poll interval (seconds) between successful polls.
        connect_timeout: Socket timeout (seconds) for connect/read operations.
        max_backoff: Maximum backoff (seconds) when repeated errors occur.
        idle_confirm: Seconds to re-check and confirm an observed "idle" state
                      before reporting it as a state change (helps avoid
                      transient idles).
    """

    def __init__(
        self,
        session_name: str,
        socket_path: str,
        queue: Optional[Queue] = None,
        on_update: Optional[Callable[[Dict[str, Any]], None]] = None,
        poll_interval: float = 0.5,
        connect_timeout: float = 1.0,
        max_backoff: float = 5.0,
        idle_confirm: float = 1.0,
    ) -> None:
        self.session_name = session_name
        self.socket_path = socket_path
        self.queue = queue
        self.on_update = on_update
        self.poll_interval = float(poll_interval)
        self.connect_timeout = float(connect_timeout)
        self.max_backoff = float(max_backoff)
        self.idle_confirm = float(idle_confirm)

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"OrchPoller-{session_name}")
        self._last_payload: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the background poller thread (no-op if already started)."""
        if not self._thread.is_alive():
            logger.info("Starting OrchestratorPoller for %s (socket=%s)", self.session_name, self.socket_path)
            self._thread.start()

    def stop(self, join_timeout: float = 1.0) -> None:
        """Signal the poller to stop and wait (best-effort) for the thread to join.

        Args:
            join_timeout: Seconds to wait for the thread to join.
        """
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=join_timeout)
        logger.info("Stopped OrchestratorPoller for %s", self.session_name)

    def is_alive(self) -> bool:
        """Return True if the internal watcher thread is alive."""
        return self._thread.is_alive()

    def get_last_state(self) -> Optional[Dict[str, Any]]:
        """Return the last observed payload from the agent, or None."""
        with self._lock:
            return None if self._last_payload is None else dict(self._last_payload)

    def wait_for_state(self, target_state: str, timeout: Optional[float] = None) -> bool:
        """Block until the polled agent reports target_state or timeout elapses.

        This helper periodically inspects the last observed payload and returns
        True if the desired state is observed within timeout seconds. It does
        not perform socket IO itself and therefore will not block on network
        operations; it simply waits for the background thread to post updates.

        Args:
            target_state: The desired agent state to wait for (e.g., "idle").
            timeout: Maximum seconds to wait; None means wait indefinitely.

        Returns:
            True if target_state was observed, False on timeout.
        """
        deadline = None if timeout is None else (time.monotonic() + float(timeout))
        while not self._stop_event.is_set():
            payload = self.get_last_state()
            if payload and str(payload.get("state", "")).lower() == str(target_state).lower():
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.1)
        return False

    # Internal methods
    def _run(self) -> None:
        """Main watcher loop run in the background thread.

        The loop makes short-lived connections to the UDS socket, reads a
        single JSON response, and notifies on payload changes. Connection
        and read errors back off exponentially up to max_backoff.
        """
        backoff = 0.5
        while not self._stop_event.is_set():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(self.connect_timeout)
                    try:
                        s.connect(self.socket_path)
                    except Exception:
                        # Could not connect; apply backoff and retry
                        logger.debug("OrchPoller(%s): connect failed, backing off %.2fs", self.session_name, backoff)
                        time.sleep(backoff)
                        backoff = min(backoff * 1.5, self.max_backoff)
                        continue

                    # Connected successfully; reset backoff and probe
                    backoff = 0.5
                    try:
                        s.sendall(b"\n")
                    except Exception:
                        # Non-fatal if send fails
                        pass

                    try:
                        data = s.recv(65536)
                    except socket.timeout:
                        data = b""
                    except Exception as exc:
                        logger.debug("OrchPoller(%s): recv error: %s", self.session_name, exc)
                        data = b""

                    if not data:
                        # No data read; wait and retry
                        time.sleep(self.poll_interval)
                        continue

                    try:
                        payload = json.loads(data.decode("utf-8", errors="replace"))
                    except Exception:
                        logger.debug("OrchPoller(%s): failed parsing JSON payload", self.session_name)
                        time.sleep(self.poll_interval)
                        continue

                    # Optional idle confirmation: if state is idle, re-check after idle_confirm seconds
                    state = str(payload.get("state", "")).lower()
                    if state == "idle" and self.idle_confirm > 0:
                        # record since and then re-probe after idle_confirm to ensure persistence
                        since_val = payload.get("since")
                        confirmed = self._confirm_idle_persistence(since_val)
                        if not confirmed:
                            # Not confirmed; continue polling
                            time.sleep(self.poll_interval)
                            continue

                    # If payload changed, update last and notify
                    with self._lock:
                        if payload != self._last_payload:
                            self._last_payload = payload
                            enriched = dict(payload)
                            enriched.setdefault("session", self.session_name)

                            # Deliver via queue first (non-blocking put)
                            if self.queue is not None:
                                try:
                                    self.queue.put_nowait(enriched)
                                except Exception:
                                    logger.exception("OrchPoller(%s): failed to enqueue payload", self.session_name)

                            # Then call callback (if provided)
                            if self.on_update:
                                try:
                                    self.on_update(enriched)
                                except Exception:
                                    logger.exception("OrchPoller(%s): on_update callback failed", self.session_name)

                    # Sleep poll_interval before next probe
                    time.sleep(self.poll_interval)
            except Exception:
                # Catch-all to prevent thread death; sleep a bit then retry
                logger.exception("OrchPoller(%s): unexpected error in watcher loop", self.session_name)
                time.sleep(min(backoff, self.max_backoff))

    def _confirm_idle_persistence(self, since_val: Optional[str]) -> bool:
        """Confirm that an observed idle state persists for idle_confirm seconds.

        This helper sleeps in small increments while checking the stop event and
        then attempts a single re-read of the socket to verify the state is still
        idle and the since value hasn't regressed.
        """
        if self.idle_confirm <= 0:
            return True
        waited = 0.0
        step = 0.1
        while waited < self.idle_confirm and not self._stop_event.is_set():
            time.sleep(step)
            waited += step
        if self._stop_event.is_set():
            return False

        # Do one quick re-probe to verify idle still holds
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self.connect_timeout)
                s.connect(self.socket_path)
                try:
                    s.sendall(b"\n")
                except Exception:
                    pass
                try:
                    data = s.recv(65536)
                except Exception:
                    return False
                if not data:
                    return False
                try:
                    payload = json.loads(data.decode("utf-8", errors="replace"))
                except Exception:
                    return False
                state = str(payload.get("state", "")).lower()
                new_since = payload.get("since")
                if state == "idle" and (since_val is None or new_since == since_val or new_since >= since_val):
                    return True
        except Exception:
            return False
        return False
