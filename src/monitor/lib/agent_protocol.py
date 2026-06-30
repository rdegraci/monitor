"""Sub-agent frame protocol (wire layer).

Implements Part 1 of docs/cache/PLAN_AGENT_ORCHESTRATION.md: the length-prefixed,
versioned, typed frame protocol spoken over the AF_UNIX channel between a parent
monitor (orchestrator) and its `monitor --agent` children (sub-agents).

This module is pure logic — stdlib only, no sockets, no monitor.config — so it
imports cleanly anywhere and is trivially unit-testable. Phase 2 (transport)
layers sockets on top of `FrameDecoder` / `encode_frame`.

Wire format (every frame):

    ┌────────────┬───────────────────────────┐
    │ uint32 BE  │  JSON body (length bytes)  │
    │  length    │                            │
    └────────────┴───────────────────────────┘

Length-prefix (not newline-delimited) because agent output legitimately
contains newlines. Frames are capped at MAX_FRAME_BYTES to stop a runaway child
from OOM-ing the orchestrator.

Envelope (the JSON body):

    {"v": 1, "type": "status", "agent_id": "a3f9", "seq": 42, "ts": 1733270400.1,
     "body": {...}}
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 1024 * 1024  # 1 MiB cap on a single frame's JSON body
_LENGTH_PREFIX_BYTES = 4       # uint32 big-endian

# --- Frame types ------------------------------------------------------------
HELLO = "hello"
STATUS = "status"
STDOUT = "stdout"
RESULT = "result"
ERROR = "error"
EXIT = "exit"
HEARTBEAT = "heartbeat"
CANCEL = "cancel"

# child → orchestrator
CHILD_TYPES = frozenset({HELLO, STATUS, STDOUT, RESULT, ERROR, EXIT, HEARTBEAT})
# orchestrator → child
ORCH_TYPES = frozenset({CANCEL})
ALL_TYPES = CHILD_TYPES | ORCH_TYPES

# A terminal frame ends an agent's lifecycle on the happy path.
TERMINAL_TYPES = frozenset({RESULT, ERROR, EXIT})


class ProtocolError(Exception):
    """Raised on a malformed/oversize/incompatible frame. Callers should treat a
    connection that produces one as failed (and, for a child, dirty-disconnect)."""


# --- Encoding ---------------------------------------------------------------

def make_frame(
    type: str,
    agent_id: str,
    seq: int,
    body: Optional[Dict[str, Any]] = None,
    ts: Optional[float] = None,
) -> Dict[str, Any]:
    """Build a frame envelope dict. ``ts`` defaults to the current wall clock."""
    if type not in ALL_TYPES:
        raise ProtocolError(f"unknown frame type: {type!r}")
    return {
        "v": PROTOCOL_VERSION,
        "type": type,
        "agent_id": agent_id,
        "seq": int(seq),
        "ts": time.time() if ts is None else ts,
        "body": body or {},
    }


def encode_frame(frame: Dict[str, Any]) -> bytes:
    """Serialize a frame dict to length-prefixed bytes.

    Raises ProtocolError if the encoded body exceeds MAX_FRAME_BYTES.
    """
    payload = json.dumps(frame, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise ProtocolError(
            f"frame too large: {len(payload)} bytes > {MAX_FRAME_BYTES} cap "
            f"(type={frame.get('type')!r}, agent_id={frame.get('agent_id')!r})"
        )
    return len(payload).to_bytes(_LENGTH_PREFIX_BYTES, "big") + payload


def encode(
    type: str,
    agent_id: str,
    seq: int,
    body: Optional[Dict[str, Any]] = None,
    ts: Optional[float] = None,
) -> bytes:
    """Convenience: make_frame(...) then encode_frame(...)."""
    return encode_frame(make_frame(type, agent_id, seq, body, ts))


# --- Decoding (partial-read tolerant) ---------------------------------------

class FrameDecoder:
    """Accumulates bytes from a stream socket and yields complete frames.

    SOCK_STREAM does not preserve message boundaries, so ``feed`` buffers
    partial data and only emits frames once their full length has arrived. A
    single ``feed`` may return zero, one, or many frames.
    """

    def __init__(self, max_frame_bytes: int = MAX_FRAME_BYTES):
        self._buf = bytearray()
        self._max = max_frame_bytes

    def feed(self, data: bytes) -> List[Dict[str, Any]]:
        """Add bytes; return all complete, validated frames now available.

        Raises ProtocolError on an oversize length prefix or a frame that fails
        envelope validation — both are unrecoverable for the connection.
        """
        if data:
            self._buf.extend(data)
        frames: List[Dict[str, Any]] = []
        while True:
            if len(self._buf) < _LENGTH_PREFIX_BYTES:
                break
            length = int.from_bytes(self._buf[:_LENGTH_PREFIX_BYTES], "big")
            if length > self._max:
                raise ProtocolError(f"declared frame size {length} exceeds cap {self._max}")
            total = _LENGTH_PREFIX_BYTES + length
            if len(self._buf) < total:
                break  # full body not arrived yet
            payload = bytes(self._buf[_LENGTH_PREFIX_BYTES:total])
            del self._buf[:total]
            frames.append(_decode_payload(payload))
        return frames

    @property
    def buffered(self) -> int:
        """Bytes currently held awaiting more data (for diagnostics/tests)."""
        return len(self._buf)


def _decode_payload(payload: bytes) -> Dict[str, Any]:
    try:
        frame = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ProtocolError(f"frame body is not valid UTF-8 JSON: {e}") from e
    return _validate(frame)


def _validate(frame: Any) -> Dict[str, Any]:
    if not isinstance(frame, dict):
        raise ProtocolError("frame must be a JSON object")
    v = frame.get("v")
    if v != PROTOCOL_VERSION:
        raise ProtocolError(f"protocol version mismatch: got {v!r}, expected {PROTOCOL_VERSION}")
    ftype = frame.get("type")
    if ftype not in ALL_TYPES:
        raise ProtocolError(f"unknown or missing frame type: {ftype!r}")
    if not isinstance(frame.get("agent_id"), str) or not frame["agent_id"]:
        raise ProtocolError("frame missing non-empty string agent_id")
    if not isinstance(frame.get("seq"), int):
        raise ProtocolError("frame missing integer seq")
    if not isinstance(frame.get("body", {}), dict):
        raise ProtocolError("frame body must be an object")
    frame.setdefault("body", {})
    return frame


# --- Typed constructors (sugar over make_frame) -----------------------------

def hello(agent_id: str, seq: int, *, depth: int, cmd: str, pid: int, name: str) -> Dict[str, Any]:
    return make_frame(HELLO, agent_id, seq, {"depth": depth, "cmd": cmd, "pid": pid, "name": name})


def status(agent_id: str, seq: int, label: str) -> Dict[str, Any]:
    return make_frame(STATUS, agent_id, seq, {"label": label})


def stdout(agent_id: str, seq: int, chunk: str) -> Dict[str, Any]:
    return make_frame(STDOUT, agent_id, seq, {"chunk": chunk})


def sanitize_usage(usage: Any) -> Optional[Dict[str, Any]]:
    """Coerce a child's cost-telemetry block to ``{model, cost_usd, total_tokens}``
    or return None. Best-effort: malformed input yields None (never raises), so a
    bad ``usage`` block is silently dropped rather than rejecting the frame.

    Used both when building a ``result`` frame (sender) and when reading one
    (orchestrator), so the contract is enforced on both ends.
    """
    if not isinstance(usage, dict):
        return None
    model = usage.get("model")
    if not isinstance(model, str) or not model:
        return None
    cost_value = usage.get("cost_usd")
    token_value = usage.get("total_tokens")
    if cost_value is None or token_value is None:
        return None
    try:
        cost = float(cost_value)
        tokens = int(token_value)
    except (TypeError, ValueError):
        return None
    if cost < 0 or tokens < 0:
        return None
    return {"model": model, "cost_usd": cost, "total_tokens": tokens}


def result(
    agent_id: str,
    seq: int,
    *,
    ok: bool,
    summary: str,
    data: Optional[Any] = None,
    usage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"ok": ok, "summary": summary}
    if data is not None:
        body["data"] = data
    clean_usage = sanitize_usage(usage)
    if clean_usage is not None:
        body["usage"] = clean_usage
    return make_frame(RESULT, agent_id, seq, body)


def error(agent_id: str, seq: int, *, kind: str, message: str, recoverable: bool = False) -> Dict[str, Any]:
    return make_frame(ERROR, agent_id, seq, {"kind": kind, "message": message, "recoverable": recoverable})


def exit_frame(agent_id: str, seq: int, code: int = 0) -> Dict[str, Any]:
    return make_frame(EXIT, agent_id, seq, {"code": code})


def heartbeat(agent_id: str, seq: int) -> Dict[str, Any]:
    return make_frame(HEARTBEAT, agent_id, seq, {})


def cancel(agent_id: str, seq: int, reason: str = "") -> Dict[str, Any]:
    return make_frame(CANCEL, agent_id, seq, {"reason": reason})


def is_terminal(frame: Dict[str, Any]) -> bool:
    """True if this frame ends the agent's lifecycle (result/error/exit)."""
    return frame.get("type") in TERMINAL_TYPES
