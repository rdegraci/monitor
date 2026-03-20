"""Monitor status store and optional UDS status server.

Provides thread-safe set_status/get_status API and a simple Unix Domain Socket
server that serves status queries. The server listens on a socket path under
user cache dir by default. Requests are JSON lines; responses are JSON.

This module is intentionally small and focused on read-only status reporting.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import appdirs

logger = logging.getLogger(__name__)

_STATE_LOCK = threading.Lock()
_STATE: Dict[str, Optional[str]] = {"state": "idle", "since": datetime.utcnow().isoformat() + "Z"}
_SERVER_THREAD: Optional[threading.Thread] = None
_SERVER_SHUTDOWN = threading.Event()
_SOCKET_PATH: Optional[Path] = None


def set_status(state: str) -> None:
    """Set the current state string ('idle' or 'working')."""
    if state not in ("idle", "working"):
        raise ValueError("Invalid state; expected 'idle' or 'working'")
    with _STATE_LOCK:
        _STATE["state"] = state
        _STATE["since"] = datetime.utcnow().isoformat() + "Z"


def get_status() -> Dict[str, str]:
    """Return a snapshot of the current status."""
    with _STATE_LOCK:
        return dict(_STATE)


def _handle_connection(conn: socket.socket) -> None:
    """Handle a single connection: read JSON request and write status response."""
    try:
        data = b""
        # read up to newline
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in chunk:
                break
        # We don't require a particular request format; ignore request body
        status = get_status()
        resp = json.dumps(status) + "\n"
        conn.sendall(resp.encode("utf-8"))
    except Exception as exc:
        logger.exception("Exception while handling status connection: %s", exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _server_loop(sock_path: Path):
    """Main server loop accepting connections on UDS socket."""
    global _SERVER_SHUTDOWN
    if sock_path.exists():
        try:
            sock_path.unlink()
        except Exception:
            logger.warning("Unable to unlink existing socket path %s", sock_path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    # Set socket file permission to user-only
    try:
        os.chmod(str(sock_path), 0o600)
    except Exception:
        logger.exception("Failed setting socket permissions")
    server.listen(5)
    logger.info("Status UDS server listening on %s", sock_path)
    server.settimeout(1.0)
    try:
        while not _SERVER_SHUTDOWN.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            threading.Thread(target=_handle_connection, args=(conn,), daemon=True).start()
    finally:
        try:
            server.close()
        except Exception:
            pass
        try:
            if sock_path.exists():
                sock_path.unlink()
        except Exception:
            pass
        logger.info("Status UDS server stopped")


def start_status_server(socket_path: Optional[str] = None) -> str:
    """Start the background UDS status server. Returns the socket path used.

    If socket_path is None, a default is chosen under the user cache dir.
    """
    global _SERVER_THREAD, _SERVER_SHUTDOWN, _SOCKET_PATH
    if _SERVER_THREAD and _SERVER_THREAD.is_alive():
        return str(_SOCKET_PATH)
    if socket_path:
        sock_path = Path(socket_path)
    else:
        base = Path(appdirs.user_cache_dir("monitor"))
        base.mkdir(parents=True, exist_ok=True)
        sock_path = base / "monitor-status.sock"
    _SOCKET_PATH = sock_path
    _SERVER_SHUTDOWN.clear()
    _SERVER_THREAD = threading.Thread(target=_server_loop, args=(sock_path,), daemon=True)
    _SERVER_THREAD.start()
    # Wait a moment for server to bind
    time.sleep(0.1)
    return str(sock_path)


def stop_status_server() -> None:
    """Signal the status server to stop and wait briefly."""
    global _SERVER_THREAD, _SERVER_SHUTDOWN
    if _SERVER_THREAD and _SERVER_THREAD.is_alive():
        _SERVER_SHUTDOWN.set()
        _SERVER_THREAD.join(timeout=2.0)

