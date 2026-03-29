"""ScreenHandler: manage interactive Monitor sub-agent sessions in screen.

This module provides ScreenHandler, a class encapsulating the logic to create
and manage interactive sub-agent sessions that run Monitor inside GNU screen.

The design intentionally keeps all screen-specific behavior centralized so the
interactive built-in can call into this helper without duplicating logic.
"""

from __future__ import annotations

import json
import logging
import os
import random
import shlex
import socket
import string
import subprocess
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import appdirs
import monitor.config as config
from .screen_handler_utils import (
    shutil_which,
    resolve_screen_token,
    find_tokens_for_name,
    parse_screen_ls_tokens,
)

logger = logging.getLogger(__name__)


class ScreenHandlerError(RuntimeError):
    """Exception raised for ScreenHandler-specific errors."""


class SubagentCreationBlocked(ScreenHandlerError):
    """Raised when sub-agent creation is blocked due to configured depth limits."""


class ScreenHandler:
    """Manage interactive sub-agent sessions using GNU screen.

    Responsibilities:
    - Generate unique session names.
    - Launch an interactive Monitor process inside a detached screen session.
    - Inject an initial prompt into the Monitor process so the sub-agent starts.
    - Provide helper APIs for listing sessions, sending input, killing sessions,
      and reading per-session metadata/logs.

    Args:
        screen_cmd: The screen executable to use (default: "screen").
        monitor_cmd: The command to launch Monitor (list form). If None, defaults
            to ["python", "-m", "monitor"].
        base_log_dir: Directory to place per-session logs. Defaults to appdirs user cache.
        base_meta_dir: Directory to place per-session metadata. Defaults to appdirs user data.
    """

    SAFE_SESSION_CHARS = set(string.ascii_lowercase + string.digits + "_-")

    def __init__(
        self,
        screen_cmd: str = "screen",
        monitor_cmd: Optional[List[str]] = None,
        base_log_dir: Optional[str] = None,
        base_meta_dir: Optional[str] = None,
    ) -> None:
        self.screen_cmd = screen_cmd
        self.monitor_cmd = monitor_cmd or ["python", "-m", "monitor"]
        self.base_log_dir = (
            Path(base_log_dir)
            if base_log_dir
            else Path(appdirs.user_cache_dir("monitor")) / "subagents"
        )
        self.base_meta_dir = (
            Path(base_meta_dir)
            if base_meta_dir
            else Path(appdirs.user_data_dir("monitor")) / "subagents"
        )
        self.base_log_dir.mkdir(parents=True, exist_ok=True)
        self.base_meta_dir.mkdir(parents=True, exist_ok=True)

        # Instance identifier: UTC timestamp + short uuid (8 hex chars)
        # Exposed as attribute for external reference.
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        short_uuid = uuid.uuid4().hex[:8]
        self.instance_id = f"{ts}_{short_uuid}"

        # Sessions index file path for this instance
        self.sessions_file = self.base_meta_dir / f"sessions_{self.instance_id}.json"

    def generate_session_name(self) -> str:
        """Generate a unique session name: YYYYMMDD_abc.

        Returns:
            A string like '20261003_ysx'.
        """
        date_part = datetime.utcnow().strftime("%Y%m%d")
        suffix = "".join(random.choices(string.ascii_lowercase, k=3))
        name = f"{date_part}_{suffix}"
        return name

    def _validate_session_name(self, name: str) -> bool:
        """Validate session name contains only safe characters."""
        if not name:
            return False
        return all(c in self.SAFE_SESSION_CHARS for c in name.replace("_", ""))

    def sanitize_prompt(self, prompt: str, max_len: int = 32_000) -> str:
        """Sanitize prompt text to remove problematic control characters.

        Args:
            prompt: Raw prompt string.
            max_len: Maximum allowed length; truncates if necessary.

        Returns:
            Sanitized prompt string safe to inject into a pty via screen stuff.
        """
        if not isinstance(prompt, str):
            prompt = str(prompt)
        # Remove C0 control characters except newline and tab
        sanitized = []
        for ch in prompt:
            code = ord(ch)
            if code < 0x20 and ch not in ("\n", "\t"):
                continue
            if code == 0x7F:
                continue
            sanitized.append(ch)
        out = "".join(sanitized)
        if len(out) > max_len:
            out = out[:max_len] + "\n...[truncated]"
        return out

    def _screen_available(self) -> bool:
        """Return True if the screen executable is available on PATH."""
        return shutil_which(self.screen_cmd) is not None

    def _run(self, args: List[str], **kwargs: Any) -> subprocess.CompletedProcess:
        """Run subprocess command and return CompletedProcess. Logs on exception."""
        try:
            logger.debug("Running subprocess: %s", args)
            return subprocess.run(args, **kwargs)
        except Exception as exc:
            logger.exception("Subprocess failed: %s", exc)
            raise ScreenHandlerError(f"Failed to run subprocess {args}: {exc}") from exc

    def load_sessions_index(self) -> List[Dict[str, Any]]:
        """Load the per-instance sessions index file.

        Returns:
            A list of session entry dicts. If the index file is missing or unreadable,
            returns an empty list.

        Entry dict keys:
            - session_name: str
            - meta_path: Optional[str]
            - created_at: str (ISO8601 UTC with 'Z' suffix)
        """
        if not self.sessions_file.exists():
            return []
        try:
            with open(self.sessions_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return data
            logger.warning("Sessions index %s did not contain a list; returning empty list", str(self.sessions_file))
            return []
        except Exception:
            logger.exception("Failed reading sessions index %s", str(self.sessions_file))
            return []

    def save_sessions_index(self, entries: List[Dict[str, Any]]) -> None:
        """Atomically save the sessions index to disk with restricted permissions.

        Args:
            entries: List of session entry dicts to persist.

        The file is written atomically using a temporary file and os.replace, and
        permissions are set to 0o600.
        """
        try:
            # Ensure parent dir exists
            self.base_meta_dir.mkdir(parents=True, exist_ok=True)
            # Create a temporary file in the same directory to ensure atomic replace works across filesystems
            tmp_fh = tempfile.NamedTemporaryFile(prefix=f"sessions_{self.instance_id}_", dir=str(self.base_meta_dir), delete=False, mode="w", encoding="utf-8")
            tmp_path = Path(tmp_fh.name)
            try:
                json.dump(entries, tmp_fh, ensure_ascii=False, indent=2)
                tmp_fh.flush()
                try:
                    os.fsync(tmp_fh.fileno())
                except Exception:
                    # Not fatal if fsync isn't available
                    pass
            finally:
                try:
                    tmp_fh.close()
                except Exception:
                    pass
            # Atomically replace
            os.replace(str(tmp_path), str(self.sessions_file))
            try:
                os.chmod(self.sessions_file, 0o600)
            except Exception:
                # Not fatal if chmod fails
                pass
        except Exception:
            logger.exception("Failed saving sessions index to %s", str(self.sessions_file))

    def add_session_to_index(self, session_name: str, meta_path: Optional[str] = None, created_at: Optional[str] = None) -> None:
        """Add or refresh a session entry in the per-instance sessions index.

        Args:
            session_name: The session's short name (e.g., '20261003_abc').
            meta_path: Optional path to the session metadata JSON file.
            created_at: Optional ISO8601 UTC timestamp string. If omitted, defaults to now.

        Behavior:
            - Avoids duplicate entries by removing any existing entry with the same session_name.
            - Prepends the new entry so index 1 is the most recent session.
        """
        if created_at is None:
            created_at = datetime.utcnow().isoformat() + "Z"
        entries = self.load_sessions_index()
        # Remove duplicates
        normalized = [e for e in entries if e.get("session_name") != session_name]
        new_entry: Dict[str, Any] = {"session_name": session_name, "created_at": created_at}
        if meta_path:
            new_entry["meta_path"] = meta_path
        # Prepend newest
        normalized.insert(0, new_entry)
        self.save_sessions_index(normalized)

    def remove_session_from_index(self, session_name: str) -> bool:
        """Remove a session entry from the per-instance sessions index.

        Args:
            session_name: The session's short name to remove.

        Returns:
            True if an entry was removed and the index was updated, False otherwise.
        """
        entries = self.load_sessions_index()
        filtered = [e for e in entries if e.get("session_name") != session_name]
        if len(filtered) == len(entries):
            return False
        self.save_sessions_index(filtered)
        return True

    def get_session_by_index(self, index: int) -> Dict[str, Any]:
        """Return a session entry by 1-based index from the sessions index.

        Args:
            index: 1-based index into the sessions index (1 is most recent).

        Returns:
            The session entry dict.

        Raises:
            ScreenHandlerError: If the index is out of range.
        """
        entries = self.load_sessions_index()
        if index < 1 or index > len(entries):
            raise ScreenHandlerError(f"Invalid session index: {index}")
        return entries[index - 1]

    def create_interactive_subagent(
        self,
        prompt: str,
        session_name: Optional[str] = None,
        *,
        max_retries: int = 30,
        retry_delay: float = 0.2,
    ) -> Dict[str, Any]:
        """Create a detached screen session running interactive Monitor and inject prompt.

        Args:
            prompt: Initial prompt to inject into the Monitor interactive session.
            session_name: Optional session name to use; if None a unique name is generated.
            max_retries: How many times to retry prompt injection.
            retry_delay: Seconds to wait between retries.

        Returns:
            A dict describing the created session (session_name, log_path, meta_path).

        Raises:
            ScreenHandlerError on failure.
        """
        # Determine current and maximum agent depths from environment or config.
        curr_depth = 0
        max_depth: Optional[int] = None
        try:
            env_val = os.environ.get("MONITOR_AGENT_DEPTH")
            if env_val is None:
                env_val = getattr(config, "MONITOR_AGENT_DEPTH", None)
            if env_val is not None:
                try:
                    curr_depth = int(env_val)
                except Exception:
                    logger.warning("Invalid MONITOR_AGENT_DEPTH value %r, defaulting to 0", env_val)
                    curr_depth = 0
        except Exception:
            logger.exception("Failed to determine MONITOR_AGENT_DEPTH; defaulting to 0")
            curr_depth = 0

        try:
            env_max = os.environ.get("MONITOR_AGENT_MAX_DEPTH")
            if env_max is None:
                env_max = getattr(config, "MONITOR_AGENT_MAX_DEPTH", None)
            if env_max is not None:
                try:
                    max_depth = int(env_max)
                except Exception:
                    logger.warning("Invalid MONITOR_AGENT_MAX_DEPTH value %r; ignoring", env_max)
                    max_depth = None
        except Exception:
            logger.exception("Failed to determine MONITOR_AGENT_MAX_DEPTH; ignoring")
            max_depth = None

        if max_depth is not None and curr_depth >= max_depth:
            logger.warning(
                "Sub-agent creation disabled: MONITOR_AGENT_MAX_DEPTH reached (depth=%d, max=%d).",
                curr_depth,
                max_depth,
            )
            raise SubagentCreationBlocked(f"Sub-agent creation disabled: MONITOR_AGENT_MAX_DEPTH reached (depth={curr_depth}, max={max_depth}).")

        if not session_name:
            session_name = self.generate_session_name()
        if not self._validate_session_name(session_name):
            raise ScreenHandlerError(
                "Generated or supplied session name contains invalid characters"
            )

        # Ensure screen exists
        if shutil_which(self.screen_cmd) is None:
            raise ScreenHandlerError("'screen' executable not found on PATH")

        # Prepare file paths
        log_path = (self.base_log_dir / f"{session_name}.log").resolve()
        meta_path = (self.base_meta_dir / f"{session_name}.json").resolve()
        socket_path = (self.base_meta_dir / f"{session_name}.sock").resolve()

        # Start detached screen with monitor
        # Use a small wrapper so Monitor runs in the pty; we do not redirect output here
        # so interactive attach will show it. We'll also write a metadata file.
        # Prepend an env wrapper to enable status reporting via a UNIX socket.
        env_vars = [
            "MONITOR_ENABLE_STATUS=1",
            f"MONITOR_STATUS_SOCKET={str(socket_path)}",
            "MONITOR_AGENT=1",
            f"MONITOR_AGENT_DEPTH={curr_depth+1}",
        ]
        if max_depth is not None:
            env_vars.append(f"MONITOR_AGENT_MAX_DEPTH={max_depth}")

        cmd = [self.screen_cmd, "-S", session_name, "-dm", "env"] + env_vars + self.monitor_cmd
        cp = self._run(cmd, check=False, capture_output=True, text=True)
        time.sleep(0.4)

        if cp.returncode != 0:
            raise ScreenHandlerError(
                f"Failed to create screen session {session_name}: {cp.stderr or cp.stdout}"
            )

        # Sanitize prompt early so metadata can include it before injection attempts.
        sanitized = self.sanitize_prompt(prompt)

        # Persist metadata early so listing/polling can observe the session.
        meta = {
            "session_name": session_name,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "prompt": sanitized,
            "log_path": str(log_path),
            "monitor_cmd": self.monitor_cmd,
            "socket_path": str(socket_path),
        }
        try:
            with open(meta_path, "w", encoding="utf-8") as fh:
                json.dump(meta, fh, ensure_ascii=False, indent=2)
            os.chmod(meta_path, 0o600)
        except Exception as exc:
            logger.exception("Failed writing metadata for %s: %s", session_name, exc)

        # Update per-instance sessions index to include this new session.
        try:
            self.add_session_to_index(session_name, meta_path=str(meta_path), created_at=meta["created_at"])
        except Exception:
            logger.exception("Failed adding session %s to sessions index %s", session_name, str(self.sessions_file))

        # Resolve the screen token for the created session. Prefer the token of form "<pid>.<name>"
        # and choose the one with the highest PID if multiple are present. If resolution fails,
        # fall back to using the session_name.
        token_str = session_name
        try:
            resolved = resolve_screen_token(self.screen_cmd, session_name)
            if resolved:
                token_str = resolved
                logger.info("Resolved screen token %s for session %s", token_str, session_name)
            else:
                logger.warning(
                    "Could not resolve screen token for session %s; falling back to session name",
                    session_name,
                )
                token_str = session_name
        except Exception:
            logger.exception("Failed to run '%s -ls' when resolving token for %s", self.screen_cmd, session_name)
            token_str = session_name

        # Update metadata with resolved screen token
        try:
            meta["screen_token"] = token_str
            with open(meta_path, "w", encoding="utf-8") as fh:
                json.dump(meta, fh, ensure_ascii=False, indent=2)
            os.chmod(meta_path, 0o600)
        except Exception:
            logger.exception("Failed updating metadata with screen_token for %s", session_name)

        # Poll for Monitor readiness by using 'screen hardcopy' into a temporary file.
        # If we see "Monitor ready!" in the hardcopy output within poll_timeout, proceed to injection.
        # Otherwise warn and proceed to injection retries.
        poll_timeout = 8.0
        poll_interval = 0.25
        found_ready = False
        tmp_path = None
        try:
            start = time.monotonic()
            # Create a temp file path that we will pass to screen hardcopy. Use delete=False
            # so screen can write to it; we'll remove it later.
            tmp_fh = tempfile.NamedTemporaryFile(delete=False)
            tmp_path = tmp_fh.name
            tmp_fh.close()
            while time.monotonic() - start < poll_timeout:
                try:
                    # Request a hardcopy of window 0 into our temp file
                    result = subprocess.run(
                        [self.screen_cmd, "-S", token_str, "-p", "0", "-X", "hardcopy", tmp_path],
                        capture_output=True,
                        text=True,
                    )
                    # If hardcopy succeeded, read and inspect the file
                    if result.returncode == 0 and os.path.exists(tmp_path):
                        try:
                            with open(tmp_path, "r", encoding="utf-8", errors="replace") as fh:
                                contents = fh.read()
                            if "Monitor ready!" in contents:
                                found_ready = True
                                break
                        except Exception:
                            # If reading fails, ignore and continue polling
                            pass
                except Exception:
                    # Ignore polling exceptions and retry until timeout
                    pass
                time.sleep(poll_interval)
            if not found_ready:
                logger.warning(
                    "Did not observe 'Monitor ready!' within %.1fs for session %s; proceeding to injection",
                    poll_timeout,
                    session_name,
                )
        finally:
            # Clean up temp file if it was created
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        # Attempt to inject the prompt
        success = False
        for attempt in range(max_retries):
            # Try to stuff into the screen window 0
            stuff_arg = sanitized + "\n"
            result = subprocess.run(
                [
                    self.screen_cmd,
                    "-S",
                    token_str,
                    "-p",
                    "0",
                    "-X",
                    "stuff",
                    stuff_arg,
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                success = True
                break
            logger.debug(
                "Prompt inject attempt %d failed: rc=%s stderr=%s stdout=%s",
                attempt,
                result.returncode,
                result.stderr,
                result.stdout,
            )
            time.sleep(retry_delay)

        if not success:
            # Do not raise on injection failure. Mark metadata and return.
            logger.warning(
                "Failed to inject prompt into session %s after %d attempts; marking metadata and returning",
                session_name,
                max_retries,
            )
            meta["injection_failed"] = True
            meta["injection_attempts"] = max_retries
            try:
                with open(meta_path, "w", encoding="utf-8") as fh:
                    json.dump(meta, fh, ensure_ascii=False, indent=2)
                os.chmod(meta_path, 0o600)
            except Exception as exc:
                logger.exception("Failed updating metadata for %s after injection failure: %s", session_name, exc)

            logger.info("Created sub-agent %s (injection failed)", session_name)
            return {"session_name": session_name, "log_path": str(log_path), "meta_path": str(meta_path)}

        # If we reached here injection succeeded; metadata already present but we can refresh timestamp
        meta["injection_failed"] = False
        try:
            with open(meta_path, "w", encoding="utf-8") as fh:
                json.dump(meta, fh, ensure_ascii=False, indent=2)
            os.chmod(meta_path, 0o600)
        except Exception:
            # Non-fatal if we can't update metadata
            logger.exception("Failed writing metadata for %s after successful injection", session_name)

        logger.info("Created sub-agent %s", session_name)
        return {"session_name": session_name, "log_path": str(log_path), "meta_path": str(meta_path)}

    def send_to_session(self, session_name: str, text: str) -> bool:
        """Send text to an existing screen session via 'stuff'.

        Returns True on success, False otherwise.
        """
        # If caller passed an explicit screen token like "<pid>.<name>" where pid is numeric,
        # treat it as an explicit token and send directly to it.
        if "." in session_name:
            left, _ = session_name.split(".", 1)
            if left.isdigit():
                token = session_name
                sanitized = self.sanitize_prompt(text)
                stuff_arg = sanitized + "\n"
                try:
                    result = subprocess.run(
                        [
                            self.screen_cmd,
                            "-S",
                            token,
                            "-p",
                            "0",
                            "-X",
                            "stuff",
                            stuff_arg,
                        ],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode != 0:
                        logger.debug(
                            "send_to_session (token) failed: rc=%s stderr=%s stdout=%s",
                            result.returncode,
                            result.stderr,
                            result.stdout,
                        )
                    return result.returncode == 0
                except Exception as exc:
                    logger.exception("Exception while sending to screen token %s: %s", token, exc)
                    return False

        # Otherwise resolve the token from 'screen -ls' by finding tokens that end with ".{session_name}"
        if not self._validate_session_name(session_name):
            raise ScreenHandlerError("Invalid session name")
        if shutil_which(self.screen_cmd) is None:
            raise ScreenHandlerError("'screen' executable not found on PATH")

        token = session_name
        try:
            resolved = resolve_screen_token(self.screen_cmd, session_name)
            if resolved:
                token = resolved
                logger.debug("Resolved screen token %s for session %s", token, session_name)
            else:
                logger.warning(
                    "Could not resolve screen token for session %s; will attempt to use session name directly",
                    session_name,
                )
                token = session_name
        except Exception as exc:
            logger.exception("Failed to list screen sessions when resolving token for %s: %s", session_name, exc)
            token = session_name

        sanitized = self.sanitize_prompt(text)
        stuff_arg = sanitized + "\n"
        try:
            result = subprocess.run(
                [
                    self.screen_cmd,
                    "-S",
                    token,
                    "-p",
                    "0",
                    "-X",
                    "stuff",
                    stuff_arg,
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logger.debug(
                    "send_to_session failed for resolved token %s: rc=%s stderr=%s stdout=%s",
                    token,
                    result.returncode,
                    result.stderr,
                    result.stdout,
                )
            return result.returncode == 0
        except Exception as exc:
            logger.exception("Exception while sending to resolved screen token %s for session %s: %s", token, session_name, exc)
            return False

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List screen sessions using 'screen -ls' and return parsed results.

        Each entry is a dict with keys 'name' and raw 'line'. This is a lightweight
        parser intended for friendly display.
        """
        if shutil_which(self.screen_cmd) is None:
            raise ScreenHandlerError("'screen' executable not found on PATH")
        result = subprocess.run([self.screen_cmd, "-ls"], capture_output=True, text=True)
        out = result.stdout or ""
        lines = out.splitlines()
        entries: List[Dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Sample lines: "\t1234.mysession\t(Detached)"
            parts = line.split()
            # find token containing a dot joining pid and name; only consider tokens with numeric pid part
            candidate = None
            for p in parts:
                if "." in p:
                    pid_part = p.split(".", 1)[0]
                    if pid_part.isdigit():
                        candidate = p
                        break
            if candidate:
                _, name = candidate.split(".", 1)
                state = "unknown"
                try:
                    meta = self.session_metadata(name)
                    if meta and "socket_path" in meta and meta["socket_path"]:
                        sock_path = meta["socket_path"]
                        # Try to connect to the UNIX socket and read a single JSON response
                        try:
                            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                                s.settimeout(1.0)
                                s.connect(sock_path)
                                try:
                                    s.sendall(b'\n')
                                except Exception:
                                    pass
                                # Read up to 64k chunks until EOF or idle timeout
                                data = bytearray()
                                try:
                                    # Improved read logic:
                                    # - Wait up to 2.0s for the first byte to arrive (first_byte_deadline).
                                    # - Use an idle timeout of 1.0s for subsequent reads.
                                    # - Continue reading chunks until recv returns empty (peer closed),
                                    #   or an idle timeout occurs after some data was received,
                                    #   or until the first-byte deadline elapses without receiving any data.
                                    first_byte_deadline = time.monotonic() + 2.0
                                    idle_timeout = 1.0
                                    while True:
                                        # Determine timeout for this recv:
                                        if not data:
                                            # Waiting for first byte; compute remaining time until deadline
                                            time_left = first_byte_deadline - time.monotonic()
                                            if time_left <= 0:
                                                # First-byte deadline elapsed without receiving data
                                                break
                                            s.settimeout(time_left)
                                        else:
                                            # We have received some data; use idle timeout for further reads
                                            s.settimeout(idle_timeout)
                                        try:
                                            chunk = s.recv(65536)
                                        except socket.timeout:
                                            # If no data has been received yet, this indicates the first-byte deadline elapsed.
                                            # If some data has been received, this indicates an idle timeout.
                                            break
                                        if not chunk:
                                            # Connection closed by peer; stop reading
                                            break
                                        data.extend(chunk)
                                except Exception:
                                    # Any read errors: proceed to parsing whatever was read, or mark unknown later
                                    pass
                                if data:
                                    try:
                                        payload = json.loads(data.decode("utf-8", errors="replace"))
                                        if isinstance(payload, dict) and "state" in payload:
                                            state = payload.get("state", "unknown")
                                        else:
                                            # If the payload is not dict, try to extract a string state
                                            if isinstance(payload, str):
                                                state = payload
                                    except Exception:
                                        state = "unknown"
                        except Exception:
                            state = "unknown"
                except Exception:
                    # Any metadata read/parsing errors result in unknown state
                    state = "unknown"

                entries.append({"name": name, "line": line, "state": state})
        return entries

    def kill_session(self, session_name: str) -> bool:
        """Kill a screen session by name (send quit). Returns True on success."""
        # If the caller passed a token like "<pid>.<name>" where pid is numeric, treat it as a token.
        if "." in session_name:
            left, right = session_name.split(".", 1)
            if left.isdigit():
                # Treat as explicit token
                try:
                    result = subprocess.run([self.screen_cmd, "-S", session_name, "-X", "quit"], capture_output=True, text=True)
                    if result.returncode == 0:
                        logger.info("Killed screen token %s", session_name)
                        # Remove from index using the short session name (after the dot)
                        try:
                            self.remove_session_from_index(right)
                        except Exception:
                            logger.exception("Failed removing session %s from index after killing token %s", right, session_name)
                        return True
                    else:
                        logger.warning("Failed to kill screen token %s: rc=%s stderr=%s stdout=%s", session_name, result.returncode, result.stderr, result.stdout)
                        return False
                except Exception as exc:
                    logger.exception("Exception while killing screen token %s: %s", session_name, exc)
                    return False

        # Otherwise, validate the session name and attempt to find matching tokens via 'screen -ls'
        if not self._validate_session_name(session_name):
            raise ScreenHandlerError("Invalid session name")
        if shutil_which(self.screen_cmd) is None:
            raise ScreenHandlerError("'screen' executable not found on PATH")

        try:
            tokens_to_kill: List[str] = find_tokens_for_name(self.screen_cmd, session_name)
            if not tokens_to_kill:
                logger.warning("No screen tokens found for session name %s", session_name)
                return False

            success_any = False
            for token in tokens_to_kill:
                try:
                    result = subprocess.run([self.screen_cmd, "-S", token, "-X", "quit"], capture_output=True, text=True)
                    if result.returncode == 0:
                        logger.info("Killed screen token %s for session %s", token, session_name)
                        success_any = True
                    else:
                        logger.warning(
                            "Failed to kill screen token %s for session %s: rc=%s stderr=%s stdout=%s",
                            token,
                            session_name,
                            result.returncode,
                            result.stderr,
                            result.stdout,
                        )
                except Exception as exc:
                    logger.exception("Exception while killing screen token %s for session %s: %s", token, session_name, exc)
            if success_any:
                try:
                    self.remove_session_from_index(session_name)
                except Exception:
                    logger.exception("Failed removing session %s from index after killing tokens", session_name)
            return success_any
        except Exception as exc:
            logger.exception("Failed to list/kill screen sessions for %s: %s", session_name, exc)
            return False

    def session_metadata(self, session_name: str) -> Optional[Dict[str, Any]]:
        """Load per-session metadata JSON if present."""
        candidate = self.base_meta_dir / f"{session_name}.json"
        if not candidate.exists():
            return None
        try:
            with open(candidate, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            logger.exception("Failed reading metadata for %s", session_name)
            return None

    def list_indexed_sessions(self, full: bool = False) -> List[Dict[str, Any]]:
        """List sessions recorded in the per-instance sessions index.

        Args:
            full: If True, include meta_path in the returned dicts. If False, omit meta_path.

        Returns:
            A list of dicts with keys:
                - index: 1-based index (1 is most recent)
                - session_name: str
                - token: resolved screen token or session_name fallback
                - state: str (e.g., 'running', 'idle', 'unknown')
                - created_at: str
                - meta_path: str (only present if full=True and available)
        """
        entries = self.load_sessions_index()
        results: List[Dict[str, Any]] = []
        for idx, entry in enumerate(entries, start=1):
            sess_name = entry.get("session_name")
            created_at = entry.get("created_at")
            meta_path = entry.get("meta_path")
            token = sess_name
            state = "unknown"
            try:
                resolved = resolve_screen_token(self.screen_cmd, sess_name)
                if resolved:
                    token = resolved
                else:
                    token = sess_name
            except Exception:
                token = sess_name

            # Try to probe state via metadata socket if available
            sock_path = None
            # If meta_path was present, try to read it to get socket_path
            if meta_path:
                try:
                    if os.path.exists(meta_path):
                        with open(meta_path, "r", encoding="utf-8") as fh:
                            m = json.load(fh)
                        if isinstance(m, dict) and "socket_path" in m and m["socket_path"]:
                            sock_path = m["socket_path"]
                except Exception:
                    logger.exception("Failed reading metadata %s for indexed session %s", str(meta_path), sess_name)
                    sock_path = None
            # If no socket from meta, try to read from base meta dir file
            if not sock_path:
                try:
                    meta_local = self.session_metadata(sess_name)
                    if meta_local and "socket_path" in meta_local and meta_local["socket_path"]:
                        sock_path = meta_local["socket_path"]
                except Exception:
                    sock_path = None

            if sock_path:
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                        s.settimeout(1.0)
                        s.connect(sock_path)
                        try:
                            s.sendall(b'\n')
                        except Exception:
                            pass
                        data = bytearray()
                        try:
                            first_byte_deadline = time.monotonic() + 2.0
                            idle_timeout = 1.0
                            while True:
                                if not data:
                                    time_left = first_byte_deadline - time.monotonic()
                                    if time_left <= 0:
                                        break
                                    s.settimeout(time_left)
                                else:
                                    s.settimeout(idle_timeout)
                                try:
                                    chunk = s.recv(65536)
                                except socket.timeout:
                                    break
                                if not chunk:
                                    break
                                data.extend(chunk)
                        except Exception:
                            pass
                        if data:
                            try:
                                payload = json.loads(data.decode("utf-8", errors="replace"))
                                if isinstance(payload, dict) and "state" in payload:
                                    state = payload.get("state", "unknown")
                                else:
                                    if isinstance(payload, str):
                                        state = payload
                            except Exception:
                                state = "unknown"
                except Exception:
                    state = "unknown"

            item: Dict[str, Any] = {
                "index": idx,
                "session_name": sess_name,
                "token": token,
                "state": state,
                "created_at": created_at,
            }
            if full and meta_path:
                item["meta_path"] = meta_path
            results.append(item)
        return results

    def tail_log(self, session_name: str, lines: int = 200) -> str:
        """Return the last `lines` of the session log if present."""
        log_file = self.base_log_dir / f"{session_name}.log"
        if not log_file.exists():
            return ""
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as fh:
                all_lines = fh.readlines()
            return "".join(all_lines[-lines:])
        except Exception:
            logger.exception("Failed to read log for %s", session_name)
            return ""


# Shared in-process ScreenHandler instance for modules to import and reuse
_GLOBAL_SCREEN_HANDLER: Optional[ScreenHandler] = None


def get_global_screen_handler() -> ScreenHandler:
    """Return the module-level shared ScreenHandler instance.

    This function implements lazy construction of the global ScreenHandler used by
    other modules. The ScreenHandler is created on first call and the same instance
    is returned on subsequent calls.

    Returns:
        ScreenHandler: The shared ScreenHandler instance.
    """
    global _GLOBAL_SCREEN_HANDLER
    if _GLOBAL_SCREEN_HANDLER is None:
        _GLOBAL_SCREEN_HANDLER = ScreenHandler()
    return _GLOBAL_SCREEN_HANDLER
