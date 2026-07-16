import json
import logging
import os
from pathlib import Path

from monitor import config

logger = logging.getLogger(__name__)
from monitor.lib.tool_definitions import AVAILABLE_TOOLS
from monitor.lib.colors import red, blue, yellow, reset
from monitor.lib import rate_limiter

from monitor.lib.protocol_engine import configure_protocol_engine_message_history
from monitor.lib.tool_profiles import refresh_tool_group_lease_for_tool
from monitor.lib.token_management import (
    count_message_tokens,
    update_token_usage,
)  # All token counting/estimation now centralized here
from monitor.lib.llm_output_utils import strip_ansi

LARGE_FILE_TOKEN_THRESHOLD = 1000
RECURSIVE_DIR_TOKEN_ESTIMATE = 500
SOURCE_MODIFICATION_TOKEN_ESTIMATE = 3000

# TC-2: cap on the depth of nested tool-call dispatches. handle_tool_call
# recurses when the model's reply also contains tool_calls; an adversarial
# prompt or runaway agent loop would otherwise stack-overflow. The active
# value lives in config.MAX_TOOL_CALL_DEPTH so it's tunable at runtime
# without an import-time freeze.

# TC-3: per-turn loop detector. Records (tool_name, canonical_args) for each
# tool call dispatched this turn. When the same signature has appeared the
# last config.MAX_REPEATED_TOOL_CALLS times in a row, handle_tool_call
# rejects the call without executing it — the model gets an error string

WRITE_GUARDED_TOOLS = {
    "bulk_replace_in_files",
    "create_file",
    "modify_source_code",
    "str_replace_based_edit_tool",
    "str_replace_editor",
    "text_file_create",
    "text_file_insert_text_at_line",
    "text_file_str_replace_in_file",
}



def _extract_single_path_target(function_args):
    """Return a single path target from a tool call.

    Args:
        function_args: Parsed tool arguments.

    Returns:
        list[str]: One target when a non-empty path is present, else empty.
    """
    path_value = function_args.get("path")
    if isinstance(path_value, str) and path_value.strip():
        return [path_value.strip()]
    return []



def _extract_source_file_target(function_args):
    """Return a source_file target from a tool call.

    Args:
        function_args: Parsed tool arguments.

    Returns:
        list[str]: One target when a non-empty source_file is present, else empty.
    """
    source_file = function_args.get("source_file")
    if isinstance(source_file, str) and source_file.strip():
        return [source_file.strip()]
    return []



def _extract_paths_targets(function_args):
    """Return explicit targets from a paths argument.

    Args:
        function_args: Parsed tool arguments.

    Returns:
        list[str]: Normalized targets from paths.

    Raises:
        ValueError: If paths contains non-string or empty entries.
    """
    paths_value = function_args.get("paths")
    if isinstance(paths_value, str):
        if paths_value.strip():
            return [paths_value.strip()]
        raise ValueError("paths must not be empty")
    if isinstance(paths_value, list):
        targets = []
        for entry in paths_value:
            if not isinstance(entry, str):
                raise ValueError("paths entries must all be strings")
            cleaned = entry.strip()
            if not cleaned:
                raise ValueError("paths entries must not be empty")
            targets.append(cleaned)
        if not targets:
            raise ValueError("paths must not be empty")
        return targets
    return []


WRITE_TARGET_EXTRACTORS = {
    "bulk_replace_in_files": _extract_paths_targets,
    "create_file": _extract_single_path_target,
    "modify_source_code": _extract_source_file_target,
    "str_replace_based_edit_tool": _extract_single_path_target,
    "str_replace_editor": _extract_single_path_target,
    "text_file_create": _extract_single_path_target,
    "text_file_insert_text_at_line": _extract_single_path_target,
    "text_file_str_replace_in_file": _extract_single_path_target,
}

_MISSING_WRITE_TARGET_EXTRACTORS = WRITE_GUARDED_TOOLS - set(WRITE_TARGET_EXTRACTORS)
if _MISSING_WRITE_TARGET_EXTRACTORS:
    missing_names = ", ".join(sorted(_MISSING_WRITE_TARGET_EXTRACTORS))
    raise RuntimeError(f"Missing write target extractors for guarded tools: {missing_names}")

_EXTRA_WRITE_TARGET_EXTRACTORS = set(WRITE_TARGET_EXTRACTORS) - WRITE_GUARDED_TOOLS
if _EXTRA_WRITE_TARGET_EXTRACTORS:
    extra_names = ", ".join(sorted(_EXTRA_WRITE_TARGET_EXTRACTORS))
    raise RuntimeError(f"Write target extractors registered for unguarded tools: {extra_names}")


def _resolve_write_scope_paths(raw_scope):
    """Return normalized allowed write scope paths from the environment.

    Args:
        raw_scope: Newline-delimited scope entries.

    Returns:
        list[Path]: Absolute normalized allowed scope paths.
    """
    allowed_paths = []
    for entry in raw_scope.splitlines():
        cleaned = entry.strip()
        if not cleaned:
            continue
        allowed_path = Path(cleaned).expanduser()
        if not allowed_path.is_absolute():
            allowed_path = Path.cwd() / allowed_path
        allowed_paths.append(allowed_path.resolve(strict=False))
    return allowed_paths


def _extract_write_targets(function_name, function_args):
    """Return normalized write targets for one guarded write tool.

    Args:
        function_name: The write-capable tool being authorized.
        function_args: Parsed tool arguments.

    Returns:
        list[str]: Raw path-like write targets supplied by the tool call.

    Raises:
        ValueError: If the tool is guarded but has no extractor or has invalid targets.
    """
    if function_name not in WRITE_GUARDED_TOOLS:
        return []
    extractor = WRITE_TARGET_EXTRACTORS.get(function_name)
    if extractor is None:
        raise ValueError(f"No write target extractor registered for {function_name}")
    return extractor(function_args)


def _path_is_within_scope(target_value, allowed_paths):
    """Return whether a target path is within any allowed delegated scope.

    Args:
        target_value: Raw target path supplied to the tool.
        allowed_paths: Normalized allowed scope paths.

    Returns:
        bool: True when the target is inside at least one allowed scope.
    """
    target = Path(target_value).expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    target = target.resolve(strict=False)

    for allowed_path in allowed_paths:
        try:
            target.relative_to(allowed_path)
            return True
        except ValueError:
            if target == allowed_path:
                return True
    return False


def _target_scope_error(function_name, target_value, allowed_paths):
    """Return a delegated-scope error for one target, if any.

    Args:
        function_name: The write-capable tool the sub-agent attempted to use.
        target_value: Raw target path or glob supplied to the tool.
        allowed_paths: Normalized allowed scope paths.

    Returns:
        str | None: Scope error string for this target, else None.
    """
    has_glob = any(char in target_value for char in "*?[]{}")
    if has_glob:
        return (
            f"Delegated sub-agent write for tool '{function_name}' must use "
            f"explicit file paths; glob targets are not allowed: {target_value}"
        )

    if _path_is_within_scope(target_value, allowed_paths):
        return None
    return (
        f"Delegated sub-agent write for tool '{function_name}' is outside the "
        f"granted scope: {target_value}"
    )


def _subagent_write_scope_error(function_name, function_args):
    """Return an error when a delegated sub-agent write is out of scope.

    Args:
        function_name: The write-capable tool the sub-agent attempted to use.
        function_args: Parsed tool arguments.

    Returns:
        str | None: A user-visible error string when the target path is out of
            scope, else None.
    """
    raw_scope = os.environ.get("MONITOR_SUBAGENT_WRITE_SCOPE", "")
    allowed_paths = _resolve_write_scope_paths(raw_scope)
    if not allowed_paths:
        return None

    try:
        targets = _extract_write_targets(function_name, function_args)
    except ValueError as exc:
        return (
            f"Delegated sub-agent write for tool '{function_name}' has invalid "
            f"targets: {exc}"
        )
    if not targets:
        return (
            f"Delegated sub-agent write access for '{function_name}' requires a "
            "path-like target, but none was provided."
        )

    for target_value in targets:
        scope_error = _target_scope_error(function_name, target_value, allowed_paths)
        if scope_error is not None:
            return scope_error

    return None


def _subagent_write_block_error(function_name, function_args):
    """Return an error when a sub-agent is denied write-tool access.

    Args:
        function_name: The write-capable tool the sub-agent attempted to use.
        function_args: Parsed tool arguments.

    Returns:
        str | None: A user-visible error string when writes are blocked, else None.
    """
    if not getattr(config, "AGENT", False):
        return None

    mode = str(getattr(config, "SUBAGENT_WRITE_ACCESS", "none")).strip().lower()
    if mode == "full":
        return None
    if mode == "none":
        return (
            f"Sub-agent write access is disabled (SUBAGENT_WRITE_ACCESS=none). "
            f"Tool '{function_name}' cannot be used in --agent mode. "
            "Report the proposed change to the orchestrator instead."
        )
    if mode == "delegated":
        if os.environ.get("MONITOR_SUBAGENT_WRITE_GRANTED") != "1":
            return (
                f"Sub-agent write access requires explicit delegation "
                f"(SUBAGENT_WRITE_ACCESS=delegated). Tool '{function_name}' cannot "
                "be used until the orchestrator grants write authority for this task."
            )
        return _subagent_write_scope_error(function_name, function_args)
    return (
        f"Sub-agent write access mode '{mode}' is not recognized. "
        f"Tool '{function_name}' is blocked in --agent mode."
    )
# routed back as the tool result so it can change strategy. Cleared when a
# new user turn enters handle_tool_call at _depth=0.
_RECENT_TOOL_CALLS: list[str] = []


def _tool_call_signature(name, args):
    """Stable hash of a tool call: 'name:<sorted-json-of-args>'.

    Sorted keys + default=str makes two calls with the same intent compare
    equal even if the model reorders kwargs or passes a non-string-keyed
    value. Falls back to repr() so a non-serializable arg never crashes
    the detector — at worst the signature becomes opaque, which is fine.
    """
    try:
        canonical = json.dumps(args, sort_keys=True, default=str) if args else "{}"
    except Exception:
        canonical = repr(args)
    return f"{name}:{canonical}"


def _check_repeated_call(name, args):
    """Append a signature; return True if the last N entries all match.

    N = config.MAX_REPEATED_TOOL_CALLS. Returns False (and still records)
    when the knob is 0 or negative — used as a kill switch.
    """
    max_reps = getattr(config, "MAX_REPEATED_TOOL_CALLS", 3)
    sig = _tool_call_signature(name, args)
    _RECENT_TOOL_CALLS.append(sig)
    if max_reps <= 0 or len(_RECENT_TOOL_CALLS) < max_reps:
        return False
    return all(s == sig for s in _RECENT_TOOL_CALLS[-max_reps:])


def parse_function_args(function_args):
    """Parse function arguments from string to dictionary"""
    try:
        if isinstance(function_args, str):
            return json.loads(function_args)
        return function_args
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing function arguments: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error parsing function arguments: {str(e)}", exc_info=True)
        raise


def _tool_telemetry_fields(tool_call, result, error):
    """Return payload-free fields for one concise tool-call telemetry line."""
    function_block = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    name = function_block.get("name", "(invalid)") if isinstance(function_block, dict) else "(invalid)"
    args_raw = function_block.get("arguments", {}) if isinstance(function_block, dict) else {}
    try:
        args = parse_function_args(args_raw)
    except Exception:
        args = {}
    path = "-"
    if isinstance(args, dict):
        for key in ("path", "file_path", "target_file", "filename", "directory"):
            value = args.get(key)
            if isinstance(value, (str, os.PathLike)) and str(value):
                path = str(value)[:240]
                break

    output_tokens = 0
    if error is None and result is not None:
        try:
            serialized = result if isinstance(result, str) else json.dumps(result, default=str)
            output_tokens = int(count_message_tokens(serialized) or 0)
        except Exception:
            logger.debug("Failed to count tool output for telemetry", exc_info=True)

    token_limit = getattr(config, "TOOL_OUTPUT_TOKEN_LIMIT", 0)
    truncated = bool(
        error is None
        and getattr(config, "RESPONSES_API", False)
        and isinstance(token_limit, int)
        and token_limit > 0
        and output_tokens > token_limit
    )
    return str(name), path, output_tokens, truncated


def _emit_tool_telemetry(tool_call, result, error, status=None):
    """Record the tool name for the turn and emit one concise telemetry line."""
    try:
        name, path, output_tokens, truncated = _tool_telemetry_fields(
            tool_call, result, error
        )
        turn_tools = getattr(config, "CURRENT_TURN_TOOL_CALLS", None)
        if not isinstance(turn_tools, list):
            turn_tools = []
        turn_tools.append(name)
        config.CURRENT_TURN_TOOL_CALLS = turn_tools
        logger.info(
            "[SPEND][TOOL] tool=%s path=%r out_tokens=%s truncated=%s status=%s",
            name,
            path,
            output_tokens,
            str(truncated).lower(),
            status or ("error" if error else "ok"),
        )
    except Exception:
        logger.debug("Failed to emit [SPEND][TOOL] telemetry", exc_info=True)


def execute_tool_call(tool_call):
    """Execute one tool and emit one short, payload-free telemetry record."""
    result = None
    error = None
    try:
        result, error = _execute_tool_call(tool_call)
        return result, error
    finally:
        _emit_tool_telemetry(tool_call, result, error)


def _execute_tool_call(tool_call):
    """Execute a single tool call and return the result

    All token counting and estimation is performed using centralized helpers in lib.token_management.

    TC-1: validate the tool_call structure before any key access. The previous
    direct ``tool_call["function"]["arguments"]`` / ``["name"]`` indexing was
    outside the try/except below, so a malformed dict raised an unhandled
    KeyError up to handle_tool_call — which had *already* appended the
    assistant message (with tool_calls) to history via extract_tool_calls.
    The result was an orphaned assistant tool_calls entry that the provider
    rejects with HTTP 400 on the next request.
    """
    logger.debug(f"Processing tool_call, type: {type(tool_call)}, value: {str(tool_call)[:300]}")

    # Structural validation — always return (None, error) on malformed input.
    if not isinstance(tool_call, dict):
        return None, f"Invalid tool call: expected dict, got {type(tool_call).__name__}"
    function_block = tool_call.get("function")
    if not isinstance(function_block, dict):
        return None, "Invalid tool call: missing or non-dict 'function' field"
    function_name = function_block.get("name")
    if not isinstance(function_name, str) or not function_name:
        return None, "Invalid tool call: missing or empty 'function.name'"
    function_args_raw = function_block.get("arguments", "")

    logger.debug(f"Executing function: {function_name}, arguments: {function_args_raw}")

    if function_name not in AVAILABLE_TOOLS:
        logger.error(f"Function {function_name} not found")
        return None, f"Key {function_name} not found in available_functions"

    try:
        function_args = parse_function_args(function_args_raw)
    except json.JSONDecodeError as e:
        error_msg = f"Error parsing arguments for {function_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg
    except Exception as e:
        error_msg = f"Unexpected error parsing arguments for {function_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg

    blocked_error = None
    if function_name in WRITE_GUARDED_TOOLS:
        blocked_error = _subagent_write_block_error(function_name, function_args)
    if blocked_error is not None:
        logger.warning(blocked_error)
        return None, blocked_error

    try:
        # Apply rate limiting for high-token operations using centralized API
        if function_name in ["cat_file", "cat_file_range", "list_directory_contents", "create_file"]:
            if function_name in ("cat_file", "cat_file_range") and "path" in function_args:
                # Use count_message_tokens for accurate estimation
                try:
                    with open(function_args["path"], "r") as f:
                        content = f.read()
                        estimated_tokens = count_message_tokens({"role": "system", "content": content})
                        if estimated_tokens > LARGE_FILE_TOKEN_THRESHOLD:
                            if rate_limiter.RATE_LIMITER is not None:
                                rate_limiter.RATE_LIMITER.wait_if_needed(estimated_tokens)
                except (FileNotFoundError, PermissionError):
                    pass

            elif function_name == "list_directory_contents" and "path" in function_args:
                if function_args.get("recursive", False):
                    # Still use conservative estimate for recursion
                    if rate_limiter.RATE_LIMITER is not None:
                        rate_limiter.RATE_LIMITER.wait_if_needed(RECURSIVE_DIR_TOKEN_ESTIMATE)

        result = AVAILABLE_TOOLS[function_name](**function_args)
        logger.debug(f"Result: {result}")

        # Record usage for high-token operations using canonical counting API
        if (
            function_name in ["cat_file", "cat_file_range", "list_directory_contents"]
            and isinstance(result, str)
        ):
            estimated_tokens = count_message_tokens({"role": "system", "content": result})
            if estimated_tokens > LARGE_FILE_TOKEN_THRESHOLD:
                if rate_limiter.RATE_LIMITER is not None:
                    rate_limiter.RATE_LIMITER.add_request(estimated_tokens)

        try:
            refresh_tool_group_lease_for_tool(function_name)
        except Exception:
            logger.debug("Failed to refresh temporary tool-group lease", exc_info=True)

        return result, None
    except TypeError as e:
        error_msg = f"Error executing {function_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg
    except json.JSONDecodeError as e:
        error_msg = f"Error parsing arguments for {function_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg
    except Exception as e:
        error_msg = f"Unexpected error executing {function_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg


def handle_tool_call(response, _depth=0):
    """Orchestrate the handling of tool calls from LLM response.

    All token counting and estimation logic is routed through lib.token_management per project policy.

    TC-2: ``_depth`` tracks nested tool-call dispatches and bails at
    MAX_TOOL_CALL_DEPTH so a runaway tool-calls chain unwinds gracefully
    instead of stack-overflowing.
    """

    # Start of a new user turn — clear the per-turn loop-detector ledger so
    # the previous turn's signatures don't bleed forward.
    if _depth == 0:
        _RECENT_TOOL_CALLS.clear()

    max_depth = config.MAX_TOOL_CALL_DEPTH
    if _depth >= max_depth:
        logger.error(
            "handle_tool_call: depth %d reached MAX_TOOL_CALL_DEPTH %d; aborting chain",
            _depth, max_depth,
        )
        return (
            f"Tool-call chain exceeded the maximum depth of {max_depth}. "
            "Stopping to prevent runaway recursion. The user can retry with a fresh prompt."
        )

    # Fire a single half-way warning as a heads-up that this turn is running
    # a long autonomous chain. Equality (not >=) ensures we log exactly once
    # per chain instead of spamming every round past the threshold.
    if _depth == max_depth // 2:
        logger.warning(
            "handle_tool_call: depth %d of %d reached half of MAX_TOOL_CALL_DEPTH "
            "(long autonomous chain). The hard abort fires at %d.",
            _depth, max_depth, max_depth,
        )

    from monitor.core.conversation import (
        extract_tool_calls,
        append_to_history_with_count,
        get_llm_completion,
        process_response_by_finish_reason,
        update_conversation_history,
    )
    from monitor.lib.reasoning_escalation import looks_like_failure

    logger.debug("Handling tool call (depth=%d)...", _depth)

    # Extract tool calls
    tool_calls = extract_tool_calls(response)

    # Error-driven reasoning escalation: track whether any tool output this
    # round looks like a failure (test/build/lint error, traceback, non-zero
    # exit). If so, after the loop we bump reasoning to "high" for the next
    # completion(s) this turn so the model reasons harder about the fix.
    turn_failure_detected = False

    # Process each tool call
    for tool_call in tool_calls:
        logger.debug(f"Processing tool_call, type: {type(tool_call)}, value: {str(tool_call)[:300]}")

        # TC-1: extract tool_call_id defensively. extract_tool_calls has
        # already appended the assistant message (with tool_calls) to history,
        # so we MUST append a result message for each tool_call_id even when
        # the tool itself fails or the dict is malformed — otherwise the
        # next provider request 400s on orphaned tool_calls.
        if isinstance(tool_call, dict):
            tool_call_id = tool_call.get("id")
        else:
            tool_call_id = getattr(tool_call, "id", None)

        # TC-3: loop detector. Inspect the call BEFORE executing — if the same
        # (name, args) has fired MAX_REPEATED_TOOL_CALLS times in a row this
        # turn, the result obviously isn't going to change. Return an error
        # string to the model so it can change strategy or ask the user.
        loop_name = None
        loop_args = None
        if isinstance(tool_call, dict):
            fn_block = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else None
            if fn_block:
                loop_name = fn_block.get("name")
                try:
                    loop_args = parse_function_args(fn_block.get("arguments", ""))
                except Exception:
                    loop_args = fn_block.get("arguments")

        # Bump the session-wide tool-call counter for every call seen here,
        # whether it ultimately executes, errors, or is rejected by the loop
        # detector. Surfaced via :dump_metrics for eval grading.
        try:
            config.SESSION_TOOL_CALL_COUNT = getattr(config, "SESSION_TOOL_CALL_COUNT", 0) + 1
        except Exception:
            logger.debug("Failed to increment SESSION_TOOL_CALL_COUNT", exc_info=True)

        if loop_name and _check_repeated_call(loop_name, loop_args):
            max_reps = getattr(config, "MAX_REPEATED_TOOL_CALLS", 3)
            logger.warning(
                "handle_tool_call: refusing repeated call to %s (>=%d times in a row this turn)",
                loop_name, max_reps,
            )
            try:
                config.SESSION_LOOP_DETECTOR_TRIPS = getattr(config, "SESSION_LOOP_DETECTOR_TRIPS", 0) + 1
            except Exception:
                logger.debug("Failed to increment SESSION_LOOP_DETECTOR_TRIPS", exc_info=True)
            result = None
            error = (
                f"Loop detected: you called {loop_name} with these exact arguments "
                f"{max_reps} times in a row. The result isn't going to change. "
                "Change your approach, try different arguments, or ask the user for guidance."
            )
            _emit_tool_telemetry(tool_call, result, error, status="loop_rejected")
        else:
            try:
                result, error = execute_tool_call(tool_call)
            except Exception as e:
                logger.error("execute_tool_call raised unexpectedly: %s", e, exc_info=True)
                result, error = None, f"Tool execution raised: {e}"

        # Create and append result message. create_tool_result_message handles
        # None / non-string tool_call_id by coercing to empty string — that
        # still produces an entry in history that pairs with the assistant
        # tool_call (the provider may then reject the empty id, but the
        # structural pairing is preserved and the failure is diagnosable).
        try:
            result_message = create_tool_result_message(result, error, tool_call_id)
            append_to_history_with_count(
                result_message, config.CONVERSATION_HISTORY, count_message_tokens, update_token_usage
            )
        except Exception as e:
            logger.error(
                "Failed to append tool-result message for tool_call_id=%r: %s",
                tool_call_id, e, exc_info=True,
            )

        # Scan both the error string and the tool's own output for failure
        # signals — a test runner can "succeed" as a tool (error is None) while
        # its stdout reports failing tests.
        if not turn_failure_detected and (
            looks_like_failure(error) or looks_like_failure(result)
        ):
            turn_failure_detected = True

        if error:
            continue

    # Error-driven reasoning escalation. If any tool result this round looked
    # like a failure, bump reasoning_effort to "high" for the remaining
    # completions this turn so the model reasons harder about the fix. One-way
    # (never downgrades) and reset per user turn in prepare_query_context, so it
    # naturally stays high until the turn ends. Read by llm_utils via
    # CURRENT_TURN_REASONING_OVERRIDE. Gated by ESCALATE_REASONING_ON_TOOL_FAILURE.
    try:
        if turn_failure_detected and getattr(
            config, "ESCALATE_REASONING_ON_TOOL_FAILURE", True
        ):
            from monitor.lib.reasoning_escalation import should_escalate

            current_effort = (
                getattr(config, "CURRENT_TURN_REASONING_OVERRIDE", None)
                or getattr(config, "REASONING_EFFORT", None)
            )
            if should_escalate(current_effort):
                # Escalate to "high", then apply the configured floor so a higher
                # REASONING_BUMP_EFFORT (e.g. "xhigh") still wins — but never
                # below "high".
                from monitor.lib.llm_model_utils import higher_reasoning_effort

                escalated = higher_reasoning_effort(
                    "high", getattr(config, "REASONING_BUMP_EFFORT", None)
                )
                config.CURRENT_TURN_REASONING_OVERRIDE = escalated
                logger.info(
                    "Tool failure detected; escalated reasoning effort to %s "
                    "for the remainder of this turn.",
                    escalated,
                )
                print(f"{yellow}[reasoning → {escalated}] tool failure detected{reset}")
    except Exception:
        logger.exception(
            "Reasoning escalation check failed; continuing at current effort."
        )

    # Get second response from LLM (token usage is recorded by get_llm_completion via monitor.lib.token_management)
    second_response, error = get_llm_completion()
    if error:
        logger.error(
            "Second get_llm_completion call failed after tool result for tool_call_id=%r: %s",
            tool_call_id, error,
            exc_info=True,
        )
        if error:
            return str(error)
        return (
            "The follow-up model request exceeded the configured input window. "
            "Please inspect the prior conversation history, the most recent tool output, "
            "and the configured model window, then try again with a shorter prompt or "
            "reduced context."
        )

    # Token accounting handled by get_llm_completion; no additional update here.

    # Process the response
    result = process_response_by_finish_reason(second_response)

    # If result is None, we need another tool call
    if result is None:
        return handle_tool_call(second_response, _depth=_depth + 1)

    # Update conversation history and return result
    update_conversation_history(
        result,
        "assistant",
        config.CONVERSATION_HISTORY,
        append_func=append_to_history_with_count,
        count_message_tokens_func=count_message_tokens,
        update_token_usage_func=update_token_usage
    )
    return result


def handle(function_call):
    """Handle a function call extracted from user prompt."""
    logger.debug("Handling function call...")

    try:
        # Parse the function call
        logger.debug(f"Processing function_call, type: {type(function_call)}, value: {str(function_call)[:300]}")
        if not isinstance(function_call, dict) and not (hasattr(function_call, 'name') and hasattr(function_call, 'arguments')):
            logger.warning(f"function_call is not a dict or suitable object. type: {type(function_call)} value: {str(function_call)[:300]}")
        function_name, function_args_raw = parse_function_call(function_call)
        print(f"{red}Function name: {function_name}, arguments: {function_args_raw}{reset}")

        # Execute the function
        result, error = execute_function(function_name, function_args_raw)

        # Process and display result
        process_function_result(result, error)

        if error:
            return error

        # Create and append function messages
        function_message, result_message = create_function_result_message(
            function_name, function_args_raw, result
        )
        append_to_history_with_count(
            function_message, config.CONVERSATION_HISTORY, count_message_tokens, update_token_usage
        )
        append_to_history_with_count(
            result_message, config.CONVERSATION_HISTORY, count_message_tokens, update_token_usage
        )

        # Get follow-up response from LLM
        second_response, error = get_llm_completion()
        if error:
            return "I apologize, but I encountered an error processing your request. Please try again."

        # Token accounting handled by get_llm_completion; no additional update here.

        # Process the response
        result = process_response_by_finish_reason(second_response)

        # Update conversation history and return result
        if result is None:
            result = "Ok."
        update_conversation_history(
            result,
            "assistant",
            config.CONVERSATION_HISTORY,
            append_func=append_to_history_with_count,
            count_message_tokens_func=count_message_tokens,
            update_token_usage_func=update_token_usage
        )

        return result

    except Exception as e:
        error_msg = f"Unexpected error in handle: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return error_msg


def create_tool_result_message(result, error, tool_call_id):
    """Create a message for tool execution result.

    This is the single normalization point for tool return values: tools may
    return a dict, a JSON string, or raw text — whatever is natural for them —
    and this function coerces all of them to a string for the model (dicts via
    json.dumps, with a str() fallback). Don't standardize tool return types
    upstream or add a tool-result path that bypasses this; the heterogeneity is
    intentional and reconciled here.

    Ensures content is a JSON-encoded string. Non-string results are JSON-serialized;
    if serialization fails, falls back to str(content). Minimal logging is emitted
    when coercion or fallback occurs.

    Note: No behavior change to message field ordering. Validates presence/type of
    tool_call_id; if missing or None, logs an error and sets it to an empty string
    to satisfy APIs that require a string identifier.
    """
    content = error if error else result

    if not isinstance(content, str):
        try:
            coerced_content = json.dumps(content, ensure_ascii=False)
            logger.debug(f"Coerced non-string tool result into JSON string for tool_call_id={tool_call_id}")
            content = coerced_content
        except Exception as e:
            logger.warning(f"Failed to JSON-encode tool result for tool_call_id={tool_call_id}; falling back to str(): {str(e)}")
            content = str(content)

    # Strip terminal color codes before the result reaches the model (Chat path).
    # This is the single normalization point for Chat tool results; the Responses
    # path is handled in build_function_call_output_item. See strip_ansi.
    content = strip_ansi(content)

    # Validate tool_call_id before returning the message
    try:
        original_tool_call_id = tool_call_id
        if tool_call_id is None:
            logger.error("tool_call_id was None when creating tool result message; normalizing to empty string. Upstream must provide non-empty string IDs.")
            tool_call_id = ""
        elif not isinstance(tool_call_id, str):
            # Coerce to string for safety while preserving information
            logger.warning(f"Non-string tool_call_id of type {type(tool_call_id)} encountered; coercing to string via str() for safety")
            try:
                tool_call_id = str(tool_call_id)
            except Exception as ce:
                logger.error(f"Failed coercing non-string tool_call_id={original_tool_call_id!r} to string; defaulting to empty string: {str(ce)}", exc_info=True)
                tool_call_id = ""
        if isinstance(tool_call_id, str) and tool_call_id == "":
            logger.error("Empty tool_call_id after validation/coercion; leaving as empty string to maintain API compatibility. No inference will be attempted; upstream should supply a non-empty ID.")
        elif not tool_call_id:
            logger.error("Falsy tool_call_id after validation/coercion; converting to empty string to maintain API compatibility.")
            tool_call_id = ""
    except Exception as e:
        logger.error(f"Failed validating/coercing tool_call_id; defaulting to empty string: {str(e)}", exc_info=True)
        tool_call_id = ""

    return {"role": "tool", "content": content, "tool_call_id": tool_call_id}


def create_function_result_message(function_name, function_args, result):
    """Create messages for function execution and result"""
    function_message = {
        "role": "assistant",
        "content": "None",
        "function_call": {"name": function_name, "arguments": json.dumps(function_args)},
    }

    result_message = {"role": "function", "name": function_name, "content": result}

    return function_message, result_message


def parse_function_call(function_call):
    """Parse a function call into name and arguments"""
    try:
        logger.debug(f"Processing function_call, type: {type(function_call)}, value: {str(function_call)[:300]}")
        if not isinstance(function_call, dict) and not (hasattr(function_call, 'name') and hasattr(function_call, 'arguments')):
            logger.warning(f"function_call is not a dict or suitable object. type: {type(function_call)} value: {str(function_call)[:300]}")
        function_name = function_call.name
        function_args = function_call.arguments
        logger.debug(f"Parsed function: {function_name}, arguments: {function_args}")
        return function_name, function_args
    except Exception as e:
        logger.error(f"Error parsing function call: {str(e)}", exc_info=True)
        raise


def process_function_result(result, error):
    """Process and display function execution result"""
    output_text = error if error else result
    print(f"{red if error else yellow}{output_text}{reset}")
    return output_text


def execute_function(function_name, function_args_raw):
    """Execute a function with given arguments

    All token counting and estimation is performed using canonical helpers from monitor.lib.token_management as per project policy.
    """
    if function_name not in AVAILABLE_TOOLS:
        logger.error(f"Function {function_name} not found")
        return None, f"Key {function_name} not found in available_functions"

    try:
        # Parse function arguments
        function_args = parse_function_args(function_args_raw)
    except json.JSONDecodeError as e:
        error_msg = f"Error parsing arguments for {function_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg
    except Exception as e:
        error_msg = f"Unexpected error parsing arguments for {function_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg

    blocked_error = None
    if function_name in WRITE_GUARDED_TOOLS:
        blocked_error = _subagent_write_block_error(function_name, function_args)
    if blocked_error is not None:
        logger.warning(blocked_error)
        return None, blocked_error

    try:

        # Apply rate limiting for high-token operations (centralized logic)
        if function_name in ["cat_file", "cat_file_range", "list_directory_contents", "modify_source_code"]:
            if function_name in ("cat_file", "cat_file_range") and "path" in function_args:
                try:
                    with open(function_args["path"], "r") as f:
                        content = f.read()
                        estimated_tokens = count_message_tokens({"role": "system", "content": content})
                        if estimated_tokens > LARGE_FILE_TOKEN_THRESHOLD:
                            if rate_limiter.RATE_LIMITER is not None:
                                rate_limiter.RATE_LIMITER.wait_if_needed(estimated_tokens)
                except (FileNotFoundError, PermissionError):
                    pass

            elif function_name == "modify_source_code" and "source_file" in function_args:
                try:
                    with open(function_args["source_file"], "r") as f:
                        content = f.read()
                        estimated_tokens = count_message_tokens({"role": "system", "content": content})
                        if "modification_request" in function_args:
                            estimated_tokens += count_message_tokens(
                                {"role": "user", "content": function_args["modification_request"]}
                            )
                        if rate_limiter.RATE_LIMITER is not None:
                            rate_limiter.RATE_LIMITER.wait_if_needed(estimated_tokens)
                except (FileNotFoundError, PermissionError):
                    pass

        configure_protocol_engine_message_history(config.CONVERSATION_HISTORY)
        result = AVAILABLE_TOOLS[function_name](**function_args)
        logger.debug(f"Function execution result: {result}")

        # Record usage for high-token operations via canonical message token count
        if (
            function_name in ["cat_file", "cat_file_range", "list_directory_contents"]
            and isinstance(result, str)
        ):
            estimated_tokens = count_message_tokens({"role": "system", "content": result})
            if estimated_tokens > LARGE_FILE_TOKEN_THRESHOLD:
                if rate_limiter.RATE_LIMITER is not None:
                    rate_limiter.RATE_LIMITER.add_request(estimated_tokens)
        elif function_name == "modify_source_code":
            # Record substantial token usage for source modifications (still conservatively estimated)
            if rate_limiter.RATE_LIMITER is not None:
                rate_limiter.RATE_LIMITER.add_request(SOURCE_MODIFICATION_TOKEN_ESTIMATE)

        try:
            refresh_tool_group_lease_for_tool(function_name)
        except Exception:
            logger.debug("Failed to refresh temporary tool-group lease", exc_info=True)

        return result, None
    except Exception as e:
        error_msg = f"Error executing {function_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg
