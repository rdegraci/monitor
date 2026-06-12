"""History and session helper commands for built-in command dispatch."""

import copy
import json
import logging
import os
import time
from typing import Any

from monitor import config
from monitor.lib.display_output import print_colored_error
from monitor.lib.system_prompt import build_system_prompt, clear_project_instructions_cache

logger = logging.getLogger(__name__)


def reset_conversation_history_command(arg: Any = None) -> None:
    """Reset conversation state to a freshly-started session baseline.

    Args:
        arg: Ignored dispatcher argument.

    Returns:
        None.
    """
    del arg
    try:
        clear_project_instructions_cache()

        config.CONVERSATION_HISTORY.clear()
        config.CONVERSATION_HISTORY.append(
            {
                "role": "system",
                "content": build_system_prompt(
                    session_id=getattr(config, "SESSION_ID", None)
                ),
            }
        )
        config.TOTAL_TOKEN_COUNT = 0
        config.SESSION_TOTAL_TOKENS = 0
        config.SESSION_COST_USD = 0.0
        config.SESSION_COMPACTION_COUNT = 0
        config.SESSION_TOOL_CALL_COUNT = 0
        config.SESSION_LOOP_DETECTOR_TRIPS = 0
        config.TURN_COSTS_USD = []
        config.TURN_ROUND_TRIPS = []
        config.CURRENT_TURN_REASONING_OVERRIDE = None
        config.RESPONSE_ID = None
        config.last_summary_time = time.time()
        print("Conversation history was reset to initial system prompt.")
    except Exception as exc:
        logger.error("Failed to reset conversation history: %s", exc, exc_info=True)


def cost_debug_command(arg: str = None) -> None:
    """Dump cost-tracking state for diagnosing the ``U:`` indicator.

    Args:
        arg: Ignored dispatcher argument.

    Returns:
        None.
    """
    del arg

    session_cost = getattr(config, "SESSION_COST_USD", 0.0) or 0.0
    session_tokens = getattr(config, "SESSION_TOTAL_TOKENS", 0) or 0
    buckets = getattr(config, "TURN_COSTS_USD", None) or []
    history = getattr(config, "CONVERSATION_HISTORY", None) or []
    user_count = sum(
        1 for message in history if isinstance(message, dict) and message.get("role") == "user"
    )
    bucket_sum = sum(buckets)

    print("=== Cost-tracking debug ===")
    print(f"SESSION_COST_USD:    ${session_cost:.6f}")
    print(f"SESSION_TOTAL_TOKENS: {session_tokens}")
    print(f"User messages in history: {user_count}")
    print(f"Per-turn buckets:    {len(buckets)} (sum: ${bucket_sum:.6f})")

    if buckets:
        user_messages = [
            message
            for message in history
            if isinstance(message, dict) and message.get("role") == "user"
        ]
        print("Bucket contents (index: value  len=N  ...tail of user message):")
        for index, value in enumerate(buckets):
            marker = "  <-- ZERO" if value == 0 else ""
            content = ""
            if index < len(user_messages):
                raw = user_messages[index].get("content", "")
                if not isinstance(raw, str):
                    raw = str(raw)
                flat = raw.replace("\n", " ").strip()
                length = len(flat)
                tail = flat[-100:] if length > 100 else flat
                content = f"  len={length}  ...{tail!r}"
            print(f"  [{index:3d}]: ${value:.6f}{marker}{content}")
    else:
        print("Bucket list is empty.")

    print()
    print("--- Invariant checks ---")
    if len(buckets) == user_count:
        print(f"OK  bucket_count == user_message_count ({user_count})")
    else:
        print_colored_error(
            f"MISMATCH bucket_count={len(buckets)} but user_message_count={user_count} "
            "— bucket-open or bucket-pop is firing for the wrong messages."
        )

    drift = session_cost - bucket_sum
    if abs(drift) < 1e-9:
        print(f"OK  sum(buckets) == cumulative (${session_cost:.6f})")
    else:
        print_colored_error(
            f"DRIFT sum(buckets)=${bucket_sum:.6f} vs cumulative=${session_cost:.6f} "
            f"(delta=${drift:.6f}) — some cost grew the cumulative but missed the bucket. "
            "Likely a silent exception in the bucket-update try/except at "
            "token_management.py:255-264."
        )


def dump_metrics_command(arg: str = None) -> None:
    """Write session metrics as JSON to a path.

    Args:
        arg: Output path.

    Returns:
        None.
    """
    path = (arg or "").strip()
    if not path:
        print_colored_error(
            "Usage: : (or /) dump_metrics <path>  — writes session metrics as JSON to <path>."
        )
        return

    expanded = os.path.abspath(os.path.expanduser(path))
    parent = os.path.dirname(expanded) or "."
    if not os.path.isdir(parent):
        print_colored_error(f"Parent directory does not exist: {parent}. Create it first.")
        return

    history = getattr(config, "CONVERSATION_HISTORY", None) or []
    user_msg_count = sum(
        1 for message in history if isinstance(message, dict) and message.get("role") == "user"
    )

    payload = {
        "schema_version": 1,
        "written_at": time.time(),
        "session_id": getattr(config, "SESSION_ID", None),
        "model": getattr(config, "MODEL", None),
        "startup_time": getattr(config, "STARTUP_TIME", None),
        "session_cost_usd": float(getattr(config, "SESSION_COST_USD", 0.0) or 0.0),
        "session_total_tokens": int(getattr(config, "SESSION_TOTAL_TOKENS", 0) or 0),
        "total_token_count": int(getattr(config, "TOTAL_TOKEN_COUNT", 0) or 0),
        "last_request_token_count": int(getattr(config, "LAST_REQUEST_TOKEN_COUNT", 0) or 0),
        "turn_costs_usd": list(getattr(config, "TURN_COSTS_USD", []) or []),
        "turn_round_trips": list(getattr(config, "TURN_ROUND_TRIPS", []) or []),
        "session_tool_call_count": int(getattr(config, "SESSION_TOOL_CALL_COUNT", 0) or 0),
        "session_loop_detector_trips": int(
            getattr(config, "SESSION_LOOP_DETECTOR_TRIPS", 0) or 0
        ),
        "session_compaction_count": int(
            getattr(config, "SESSION_COMPACTION_COUNT", 0) or 0
        ),
        "conversation_length": len(history),
        "user_message_count": user_msg_count,
    }

    try:
        with open(expanded, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, indent=2, sort_keys=True)
            file_handle.write("\n")
    except OSError as exc:
        print_colored_error(f"Failed to write metrics to {expanded}: {exc}")
        return

    print(f"Wrote metrics to {expanded}")


def dump_history_command(arg: str = None) -> None:
    """Write the full conversation history as JSON to a path.

    Args:
        arg: Output path.

    Returns:
        None.
    """
    path = (arg or "").strip()
    if not path:
        print_colored_error(
            "Usage: : (or /) dump_history <path>  — writes conversation history as JSON to <path>."
        )
        return

    expanded = os.path.abspath(os.path.expanduser(path))
    parent = os.path.dirname(expanded) or "."
    if not os.path.isdir(parent):
        print_colored_error(f"Parent directory does not exist: {parent}. Create it first.")
        return

    history = getattr(config, "CONVERSATION_HISTORY", None) or []
    history_copy = copy.deepcopy(list(history))

    payload = {
        "schema_version": 1,
        "written_at": time.time(),
        "session_id": getattr(config, "SESSION_ID", None),
        "model": getattr(config, "MODEL", None),
        "conversation": history_copy,
    }

    try:
        with open(expanded, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, indent=2, default=str)
            file_handle.write("\n")
    except OSError as exc:
        print_colored_error(f"Failed to write history to {expanded}: {exc}")
        return

    print(f"Wrote conversation history ({len(history_copy)} messages) to {expanded}")


def _format_elapsed(seconds: float) -> str:
    """Render a positive elapsed-time delta as a short human string.

    Args:
        seconds: Elapsed seconds.

    Returns:
        Human-readable relative age string.
    """
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def load_history_command(arg: str = None) -> None:
    """Replace current conversation history with a saved transcript.

    Args:
        arg: Input path.

    Returns:
        None.
    """
    path = (arg or "").strip()
    if not path:
        print_colored_error(
            "Usage: : (or /) load_history <path>  — load a saved conversation JSON."
        )
        return

    expanded = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(expanded):
        print_colored_error(f"File not found: {expanded}")
        return

    try:
        with open(expanded, "r", encoding="utf-8") as file_handle:
            envelope = json.load(file_handle)
    except json.JSONDecodeError as exc:
        print_colored_error(f"Failed to parse {expanded} as JSON: {exc}")
        return
    except OSError as exc:
        print_colored_error(f"Failed to read {expanded}: {exc}")
        return

    if not isinstance(envelope, dict):
        print_colored_error(
            f"{expanded}: expected a JSON object envelope, got {type(envelope).__name__}. "
            "Was this file written by :dump_history?"
        )
        return

    schema = envelope.get("schema_version")
    if schema != 1:
        print_colored_error(
            f"{expanded}: schema_version={schema!r}, expected 1. "
            "This file may have been written by a future version of monitor."
        )
        return

    conversation = envelope.get("conversation")
    if not isinstance(conversation, list):
        print_colored_error(
            f"{expanded}: 'conversation' must be a list, got "
            f"{type(conversation).__name__}."
        )
        return

    prior_count = len(getattr(config, "CONVERSATION_HISTORY", []) or [])
    config.CONVERSATION_HISTORY.clear()
    config.CONVERSATION_HISTORY.extend(conversation)
    config.TOTAL_TOKEN_COUNT = 0
    config.SESSION_TOTAL_TOKENS = 0
    config.SESSION_COST_USD = 0.0
    config.SESSION_COMPACTION_COUNT = 0
    config.SESSION_TOOL_CALL_COUNT = 0
    config.SESSION_LOOP_DETECTOR_TRIPS = 0
    config.TURN_COSTS_USD = []
    config.TURN_ROUND_TRIPS = []
    config.CURRENT_TURN_REASONING_OVERRIDE = None
    config.RESPONSE_ID = None
    config.last_summary_time = time.time()

    written_at = envelope.get("written_at")
    if isinstance(written_at, (int, float)) and written_at > 0:
        elapsed = time.time() - written_at
        elapsed_str = _format_elapsed(elapsed)
        stale_warning = (
            f" Saved {elapsed_str} — tool results (file contents, listings) "
            "may be stale relative to current filesystem state."
        )
    else:
        stale_warning = ""

    src_session = envelope.get("session_id") or "(unknown)"
    src_model = envelope.get("model") or "(unknown)"
    print(
        f"Loaded {len(conversation)} messages from {expanded} "
        f"(replaced {prior_count} in current history).{stale_warning} "
        f"Source session_id={src_session!r}, original model={src_model!r}."
    )
