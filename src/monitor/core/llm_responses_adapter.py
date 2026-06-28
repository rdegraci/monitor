import logging
import json
import threading
import signal
import uuid
from copy import deepcopy
from openai import OpenAI

XAI_BASE_URL = "https://api.x.ai/v1"
XAI_MODEL_PREFIX = "xai/"

from monitor import config
from monitor.core.tooling import execute_tool_call
from monitor.lib.message_utils import normalize_message, sanitize_messages
from monitor.lib.token_management import count_message_tokens, update_token_usage, token_budgeter
from monitor.lib import rate_limiter
from monitor.lib.llm_utils import (
    dict_to_attr, 
    validate_tool_message_order, 
    strip_openai_prefix,
    prepare_response_messages,
    estimate_response_tokens,
    get_tools_for_model,
    convert_response_format,
    handle_response_errors,
    build_function_call_output_item,
    serialize_tool_output,
    build_summarization_followup_params,
    truncate_to_token_limit,
    )
from monitor.lib.tool_loading import function_descriptions
from monitor.lib.progress import progress_dots
from monitor.lib.llm_utils import is_reasoning_model
from monitor.lib.llm_model_utils import resolve_turn_model
from monitor.lib.colors import yellow, reset

logger = logging.getLogger(__name__)

client = None

# Constants
TYPE_KEY = "type"
NAME_KEY = "name"
DESCRIPTION_KEY = "description"
DEFAULT_TOOL_TYPE = "function"
PARAMETERS_PROPERTIES_KEY = "properties"
PARAMETERS_REQUIRED_KEY = "required"
PARAMETERS_TYPE_OBJECT = "object"

ROLE_KEY = "role"
SYSTEM_ROLE = "system"
CONTENT_KEY = "content"
USER_ROLE = "user"

CHOICES_KEY = "choices"
MESSAGE_KEY = "message"

FUNCTION_CALL_TYPE = "function_call"
TOOL_CALL_TYPE = "tool_call"
FUNCTION_TOOL_CALL_TYPES = (FUNCTION_CALL_TYPE, TOOL_CALL_TYPE)
FUNCTION_CALL_OUTPUT_TYPE = "function_call_output"
REQUEST_PARAM_MODEL = "model"
REQUEST_PARAM_INPUT = "input"
REQUEST_PREV_RESPONSE_ID = "previous_response_id"
REQUEST_PARAM_TOOLS = "tools"
REQUEST_PARAM_TOOL_CHOICE = "tool_choice"
REQUEST_PARAM_TEMPERATURE = "temperature"
REQUEST_PARAM_TOP_P = "top_p"
REQUEST_PARAM_FREQUENCY_PENALTY = "frequency_penalty"
REQUEST_PARAM_PRESENCE_PENALTY = "presence_penalty"
REQUEST_PARAM_MAX_OUTPUT_TOKENS = "max_output_tokens"
OUTPUT_KEY = "output"
OUTPUT_TEXT_ATTR = "output_text"
ID_KEY = "id"
USAGE_KEYS = ("total_tokens", "total_token_count", "total")
ARGUMENTS_KEY = "arguments"
ARGS_KEY = "args"
TOOL_NAME_KEYS = ("tool", "tool_name")
CALL_ID_KEYS = ("call_id", "id")
SERIALIZATION_FAILED_STR = '{"error": "serialization_failed"}'
TEXT_KEY = "text"
MESSAGE_CONTENT_LIST_ITEM_KEYS = ("content", "text", "message")

# WARNING: Larger iterations count can increase costs, runtime, and 
# risk of runaway function-call loops, but allow the LLM to be more agentic
MAX_FUNCTION_CALL_ITERATIONS = 256
SUMMARY_MAX_OUTPUT_TOKENS = 2048
FOLLOWUP_REQUEST_CLASS_FRESH = "fresh_request"
FOLLOWUP_REQUEST_CLASS_CHAINED = "chained_user_followup"
FOLLOWUP_REQUEST_CLASS_TOOL = "tool_result_followup"
FOLLOWUP_REQUEST_CLASS_SUMMARIZATION = "summarization_followup"
FOLLOWUP_BUDGET_DECISION_SEND = "send"
FOLLOWUP_BUDGET_DECISION_SEND_TRIMMED = "send_trimmed"
FOLLOWUP_BUDGET_DECISION_FALLBACK = "fallback"
FOLLOWUP_BUDGET_DECISION_UNKNOWN = "unknown_budget"


def _resolve_responses_turn_settings():
    """Resolve the effective model and output budget for this Responses turn."""
    base_model = getattr(config, "MODEL", "") or ""
    prefix = getattr(config, "REASONING_MODEL_PREFIX", None)
    override = getattr(config, "CURRENT_TURN_REASONING_OVERRIDE", None)
    collation = bool(getattr(config, "CURRENT_TURN_IS_COLLATION", False))

    resolved_model = resolve_turn_model(
        base_model,
        getattr(config, "ADV_REASONING_MODEL", None),
        bool(override),
        prefix or "",
        orchestrator_model=getattr(config, "ORCHESTRATOR_MODEL", None),
        collation_active=collation,
    )
    request_model = strip_openai_prefix(resolved_model)
    reasoning_model = is_reasoning_model(resolved_model, prefix)

    max_output_tokens = getattr(config, "MAX_COMPLETION_TOKENS", None)
    if reasoning_model:
        max_output_tokens = getattr(config, "REASONING_MAX_COMPLETION_TOKENS", None)
        adv_out = getattr(config, "ADV_REASONING_MODEL_OUTPUT_WINDOW", None)
        if (
            resolved_model == getattr(config, "ADV_REASONING_MODEL", None)
            and isinstance(adv_out, int)
            and adv_out > 0
            and isinstance(max_output_tokens, int)
            and max_output_tokens > 0
        ):
            max_output_tokens = min(max_output_tokens, adv_out)

    return resolved_model, request_model, reasoning_model, max_output_tokens


def _maybe_escalate_reasoning_on_tool_failure(result, error):
    """Apply tool-failure reasoning escalation for the Responses tool loop."""
    try:
        if not getattr(config, "ESCALATE_REASONING_ON_TOOL_FAILURE", True):
            return
        from monitor.lib.reasoning_escalation import looks_like_failure, should_escalate
        if not (looks_like_failure(error) or looks_like_failure(result)):
            return

        current_effort = (
            getattr(config, "CURRENT_TURN_REASONING_OVERRIDE", None)
            or getattr(config, "REASONING_EFFORT", None)
        )
        if not should_escalate(current_effort):
            return

        from monitor.lib.llm_model_utils import higher_reasoning_effort

        escalated = higher_reasoning_effort(
            "high", getattr(config, "REASONING_BUMP_EFFORT", None)
        )
        config.CURRENT_TURN_REASONING_OVERRIDE = escalated
        logger.info(
            "Tool failure detected in Responses tool loop; escalated reasoning effort to %s "
            "for the remainder of this turn.",
            escalated,
        )
        print(f"{yellow}[reasoning → {escalated}] tool failure detected{reset}")
    except Exception:
        logger.exception(
            "Reasoning escalation check failed in Responses tool loop; continuing at current effort."
        )


def _get_followup_base_safety_ratio():
    value = getattr(config, "FOLLOWUP_BASE_SAFETY_RATIO", 0.85)
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 < float(value) <= 1
    ):
        return float(value)
    return 0.85


def _get_followup_toplevel_reserve_tokens():
    value = getattr(config, "FOLLOWUP_TOPLEVEL_RESERVE_TOKENS", 256)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 256
    return max(0, parsed)


def _get_followup_hidden_chain_reserve_by_class():
    defaults = {
        FOLLOWUP_REQUEST_CLASS_FRESH: 0,
        FOLLOWUP_REQUEST_CLASS_CHAINED: 2000,
        FOLLOWUP_REQUEST_CLASS_TOOL: 4000,
        FOLLOWUP_REQUEST_CLASS_SUMMARIZATION: 2000,
    }
    raw = getattr(config, "FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS", None)
    if not isinstance(raw, dict):
        return defaults
    merged = dict(defaults)
    for key, value in raw.items():
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed < 0:
            continue
        merged[str(key)] = parsed
    return merged


def _get_followup_hidden_chain_reserve_per_depth():
    value = getattr(config, "FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH", 1000)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 1000
    return max(0, parsed)


def _get_followup_hidden_chain_reserve_cap_ratio():
    value = getattr(config, "FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO", 0.5)
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 <= float(value) <= 1
    ):
        return float(value)
    return 0.5


def _get_followup_chained_reserve_rt_bounds():
    min_value = getattr(config, "FOLLOWUP_CHAINED_RESERVE_MIN_RT", 20)
    max_value = getattr(config, "FOLLOWUP_CHAINED_RESERVE_MAX_RT", 45)
    try:
        min_rt = int(min_value)
    except (TypeError, ValueError):
        min_rt = 20
    try:
        max_rt = int(max_value)
    except (TypeError, ValueError):
        max_rt = 45
    if max_rt <= min_rt:
        max_rt = min_rt + 1
    return max(0, min_rt), max_rt


def _get_followup_chained_reserve_max_tokens():
    value = getattr(config, "FOLLOWUP_CHAINED_RESERVE_MAX_TOKENS", 8000)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 8000
    return max(0, parsed)


def _get_followup_dynamic_chained_reserve_enabled():
    return bool(getattr(config, "FOLLOWUP_DYNAMIC_CHAINED_RESERVE", True))


def _get_followup_tool_omission_hints_enabled():
    return bool(getattr(config, "ENABLE_FOLLOWUP_TOOL_OMISSION_HINTS", False))


def _get_followup_show_recovery_notices():
    return bool(getattr(config, "FOLLOWUP_SHOW_RECOVERY_NOTICES", True))


def compute_followup_hidden_chain_reserve(request_class, *, iteration=0, input_window=None):
    """Compute the hidden-chain reserve for a follow-up request.

    Args:
        request_class: The classified follow-up request type.
        iteration: The current tool-loop iteration count.
        input_window: Optional model input window for reserve capping.

    Returns:
        int: The hidden-chain reserve token budget.
    """
    hidden_chain_reserve_by_class = _get_followup_hidden_chain_reserve_by_class()
    try:
        hidden_base = int(hidden_chain_reserve_by_class.get(request_class, 0) or 0)
    except (TypeError, ValueError):
        hidden_base = 0
    hidden_base = max(0, hidden_base)

    if (
        request_class == FOLLOWUP_REQUEST_CLASS_CHAINED
        and _get_followup_dynamic_chained_reserve_enabled()
    ):
        min_rt, max_rt = _get_followup_chained_reserve_rt_bounds()
        max_tokens = _get_followup_chained_reserve_max_tokens()
        rt_count = max(0, int(iteration))
        if rt_count <= min_rt:
            hidden_base = hidden_base
        elif rt_count >= max_rt:
            hidden_base = max(hidden_base, max_tokens)
        else:
            progress = float(rt_count - min_rt) / float(max_rt - min_rt)
            scaled = round(hidden_base + progress * (max_tokens - hidden_base))
            hidden_base = max(hidden_base, int(scaled))

    depth_reserve = 0
    if request_class == FOLLOWUP_REQUEST_CLASS_TOOL:
        depth_growth = max(0, int(iteration)) * max(
            0,
            int(_get_followup_hidden_chain_reserve_per_depth() or 0),
        )
        cap_ratio = _get_followup_hidden_chain_reserve_cap_ratio()
        if not isinstance(input_window, int) or input_window <= 0:
            input_window = _resolve_model_input_window()
        usable_window = 0
        if isinstance(input_window, int) and input_window > 0:
            usable_window = int(input_window * _get_followup_base_safety_ratio())
        depth_cap = max(0, int(usable_window * float(cap_ratio)))
        depth_reserve = min(depth_growth, depth_cap)

    return hidden_base + depth_reserve


def _resolve_model_input_window():
    iw = getattr(config, "MODEL_INPUT_WINDOW", None)
    cw = getattr(config, "MODEL_CONTEXT_WINDOW", None)
    return iw if isinstance(iw, int) and iw > 0 else (cw if isinstance(cw, int) and cw > 0 else None)


def _get_structural_token_encoder(model_name=None):
    import tiktoken

    encoder = None
    if model_name:
        try:
            from monitor.lib.llm_model_utils import get_model_head

            encoding_model = get_model_head(
                str(model_name),
                {
                    "gpt-5.1": "gpt-5",
                    "gpt-5": "gpt-5",
                    "gpt-4.1": "gpt-4.1",
                    "gpt-4o": "gpt-4o",
                    "gpt-4": "gpt-4",
                    "o4-mini": "o4-mini",
                },
            )
            if encoding_model:
                encoder = tiktoken.encoding_for_model(encoding_model)
        except Exception:
            logger.debug(
                "Falling back to cl100k_base for structural token counting on model=%r",
                model_name,
                exc_info=True,
            )
    if encoder is None:
        encoder = tiktoken.get_encoding("cl100k_base")
    return encoder


def count_serialized_structure_tokens(obj, model_name=None):
    """Count tokens for a serialized structured object.

    This helper is reserved for full-request reserve measurement. It token-counts
    `json.dumps(...)` output rather than relying on text-only message counting.
    """
    try:
        serialized = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        serialized = json.dumps(str(obj), sort_keys=True, ensure_ascii=False)
    try:
        encoder = _get_structural_token_encoder(model_name)
        return len(encoder.encode(serialized))
    except Exception:
        logger.exception("Failed structural token counting; falling back to text token estimate")
        return count_message_tokens(serialized)


def measure_followup_request_reserves(params, *, model_name=None):
    """Measure the known reserve buckets for a follow-up request.

    Phase 2 teaches the reserve calculator the exact structural costs of the
    tool catalog and the function_call_output item shells. The visible payload
    estimate still comes from count_message_tokens on the raw output text.
    """
    if not isinstance(params, dict):
        return {
            "tool_schema_reserve_tokens": 0,
            "structured_payload_reserve_tokens": 0,
        }

    tool_schema_reserve_tokens = 0
    if params.get(REQUEST_PARAM_TOOLS):
        tool_payload = {
            REQUEST_PARAM_TOOLS: params.get(REQUEST_PARAM_TOOLS),
        }
        if REQUEST_PARAM_TOOL_CHOICE in params:
            tool_payload[REQUEST_PARAM_TOOL_CHOICE] = params.get(REQUEST_PARAM_TOOL_CHOICE)
        tool_schema_reserve_tokens = count_serialized_structure_tokens(
            tool_payload,
            model_name=model_name,
        )

    structured_payload_reserve_tokens = 0
    request_input = params.get(REQUEST_PARAM_INPUT)
    if isinstance(request_input, list):
        for item in request_input:
            if not (isinstance(item, dict) and item.get(TYPE_KEY) == FUNCTION_CALL_OUTPUT_TYPE):
                continue
            full_item_tokens = count_serialized_structure_tokens(item, model_name=model_name)
            output_value = item.get(OUTPUT_KEY, "")
            if output_value is None:
                output_value = ""
            if not isinstance(output_value, str):
                try:
                    output_value = json.dumps(output_value, sort_keys=True, ensure_ascii=False, default=str)
                except Exception:
                    output_value = str(output_value)
            output_text_tokens = count_message_tokens(output_value)
            structured_payload_reserve_tokens += max(0, full_item_tokens - output_text_tokens)

    return {
        "tool_schema_reserve_tokens": tool_schema_reserve_tokens,
        "structured_payload_reserve_tokens": structured_payload_reserve_tokens,
    }


def classify_followup_request(params):
    """Classify a Responses follow-up request shape.

    Pure helper: depends only on the supplied params.
    """
    if not isinstance(params, dict):
        return FOLLOWUP_REQUEST_CLASS_FRESH

    previous_response_id = params.get(REQUEST_PREV_RESPONSE_ID)
    request_input = params.get(REQUEST_PARAM_INPUT)
    has_tools = bool(params.get(REQUEST_PARAM_TOOLS))

    if previous_response_id:
        if isinstance(request_input, list):
            has_function_outputs = any(
                isinstance(item, dict) and item.get(TYPE_KEY) == FUNCTION_CALL_OUTPUT_TYPE
                for item in request_input
            )
            has_non_function_output_items = any(
                not (isinstance(item, dict) and item.get(TYPE_KEY) == FUNCTION_CALL_OUTPUT_TYPE)
                for item in request_input
            )
            if has_function_outputs:
                if not has_tools and has_non_function_output_items:
                    return FOLLOWUP_REQUEST_CLASS_SUMMARIZATION
                return FOLLOWUP_REQUEST_CLASS_TOOL
        return FOLLOWUP_REQUEST_CLASS_CHAINED
    return FOLLOWUP_REQUEST_CLASS_FRESH


def calculate_followup_payload_budget(
    *,
    request_class,
    input_window,
    base_safety_ratio,
    hidden_chain_reserve_by_class,
    hidden_chain_reserve_per_depth,
    hidden_chain_reserve_cap_ratio,
    top_level_reserve_tokens,
    iteration=0,
    tool_schema_reserve_tokens=0,
    structured_payload_reserve_tokens=0,
):
    """Pure full-request reserve calculator for Responses follow-ups."""
    if not isinstance(input_window, int) or input_window <= 0:
        return {
            "request_class": request_class,
            "model_input_window": input_window,
            "usable_window": None,
            "hidden_chain_reserve": 0,
            "tool_schema_reserve": 0,
            "structured_payload_reserve": 0,
            "top_level_reserve": 0,
            "payload_budget": None,
            "decision": FOLLOWUP_BUDGET_DECISION_UNKNOWN,
        }

    usable_window = int(input_window * base_safety_ratio)
    hidden_chain_reserve = compute_followup_hidden_chain_reserve(
        request_class,
        iteration=iteration,
        input_window=input_window,
    )
    try:
        tool_schema_reserve = max(0, int(tool_schema_reserve_tokens or 0))
    except (TypeError, ValueError):
        tool_schema_reserve = 0
    try:
        structured_payload_reserve = max(0, int(structured_payload_reserve_tokens or 0))
    except (TypeError, ValueError):
        structured_payload_reserve = 0
    try:
        top_level_reserve = max(0, int(top_level_reserve_tokens or 0))
    except (TypeError, ValueError):
        top_level_reserve = 0

    payload_budget = (
        usable_window
        - hidden_chain_reserve
        - tool_schema_reserve
        - structured_payload_reserve
        - top_level_reserve
    )
    decision = (
        FOLLOWUP_BUDGET_DECISION_SEND
        if payload_budget > 0
        else FOLLOWUP_BUDGET_DECISION_FALLBACK
    )
    return {
        "request_class": request_class,
        "model_input_window": input_window,
        "usable_window": usable_window,
        "hidden_chain_reserve": hidden_chain_reserve,
        "tool_schema_reserve": tool_schema_reserve,
        "structured_payload_reserve": structured_payload_reserve,
        "top_level_reserve": top_level_reserve,
        "payload_budget": payload_budget,
        "decision": decision,
    }




def infer_followup_iteration(params, default_iteration=0):
    """Infer a follow-up iteration count from runtime state and request shape.

    Args:
        params: The request payload being budgeted.
        default_iteration: Fallback iteration to use when no better signal exists.

    Returns:
        int: The inferred non-negative iteration count.
    """
    try:
        inferred_iteration = int(default_iteration or 0)
    except (TypeError, ValueError):
        inferred_iteration = 0
    inferred_iteration = max(0, inferred_iteration)

    if not isinstance(params, dict):
        return inferred_iteration

    if not params.get(REQUEST_PREV_RESPONSE_ID):
        return inferred_iteration

    request_class = classify_followup_request(params)
    if request_class != FOLLOWUP_REQUEST_CLASS_CHAINED:
        return inferred_iteration

    round_trips = getattr(config, "TURN_ROUND_TRIPS", None)
    if not isinstance(round_trips, list) or not round_trips:
        return inferred_iteration

    current_round_trip_count = round_trips[-1]
    try:
        current_round_trip_count = int(current_round_trip_count or 0)
    except (TypeError, ValueError):
        return inferred_iteration

    return max(inferred_iteration, max(0, current_round_trip_count))
def budget_followup_request(params, *, iteration=0, input_window=None):
    """Budget a follow-up request against the reserve-aware policy.

    Returns a copy of params plus a budget-report dictionary for logging and
    admission decisions.
    """
    params_copy = deepcopy(params) if isinstance(params, dict) else {}
    request_class = classify_followup_request(params_copy)
    effective_iteration = infer_followup_iteration(
        params_copy,
        default_iteration=iteration,
    )
    resolved_input_window = (
        input_window
        if isinstance(input_window, int) and input_window > 0
        else _resolve_model_input_window()
    )
    model_name = params_copy.get(REQUEST_PARAM_MODEL) or getattr(config, "MODEL", None)
    measured_reserves = measure_followup_request_reserves(
        params_copy,
        model_name=model_name,
    )
    budget = calculate_followup_payload_budget(
        request_class=request_class,
        input_window=resolved_input_window,
        base_safety_ratio=_get_followup_base_safety_ratio(),
        hidden_chain_reserve_by_class=_get_followup_hidden_chain_reserve_by_class(),
        hidden_chain_reserve_per_depth=_get_followup_hidden_chain_reserve_per_depth(),
        hidden_chain_reserve_cap_ratio=_get_followup_hidden_chain_reserve_cap_ratio(),
        top_level_reserve_tokens=_get_followup_toplevel_reserve_tokens(),
        iteration=effective_iteration,
        tool_schema_reserve_tokens=measured_reserves.get("tool_schema_reserve_tokens", 0),
        structured_payload_reserve_tokens=measured_reserves.get(
            "structured_payload_reserve_tokens",
            0,
        ),
    )

    payload_budget = budget.get("payload_budget")
    request_input = params_copy.get(REQUEST_PARAM_INPUT)
    if (
        request_class == FOLLOWUP_REQUEST_CLASS_CHAINED
        and params_copy.get(REQUEST_PREV_RESPONSE_ID)
        and isinstance(payload_budget, int)
        and payload_budget > 0
        and isinstance(request_input, str)
    ):
        logger.info(
            "Skipping local follow-up payload admission for chained previous_response_id request; provider-side retained context is not locally measurable (payload_budget=%s, input_type=%s)",
            payload_budget,
            type(request_input).__name__,
        )
        budget["decision"] = FOLLOWUP_BUDGET_DECISION_UNKNOWN
        budget["payload_budget"] = None

    return params_copy, budget


def _build_context_length_debug_info(params, *, model_name=None):
    """Build structured diagnostics for a context-length failure.

    Args:
        params: The request payload sent to the Responses API.
        model_name: Optional model name used for structural token counting.

    Returns:
        dict: Best-effort request-shape and budgeting diagnostics.
    """
    if not isinstance(params, dict):
        params = {}

    request_input = params.get(REQUEST_PARAM_INPUT)
    request_class = classify_followup_request(params)
    effective_iteration = infer_followup_iteration(params, default_iteration=0)
    measured_reserves = measure_followup_request_reserves(
        params,
        model_name=model_name,
    )
    input_window = _resolve_model_input_window()
    budget = calculate_followup_payload_budget(
        request_class=request_class,
        input_window=input_window,
        base_safety_ratio=_get_followup_base_safety_ratio(),
        hidden_chain_reserve_by_class=_get_followup_hidden_chain_reserve_by_class(),
        hidden_chain_reserve_per_depth=_get_followup_hidden_chain_reserve_per_depth(),
        hidden_chain_reserve_cap_ratio=_get_followup_hidden_chain_reserve_cap_ratio(),
        top_level_reserve_tokens=_get_followup_toplevel_reserve_tokens(),
        iteration=effective_iteration,
        tool_schema_reserve_tokens=measured_reserves.get("tool_schema_reserve_tokens", 0),
        structured_payload_reserve_tokens=measured_reserves.get(
            "structured_payload_reserve_tokens",
            0,
        ),
    )

    input_text_tokens = None
    input_serialized_tokens = None
    input_item_count = len(request_input) if isinstance(request_input, list) else None
    function_call_output_count = 0
    input_preview = None
    if isinstance(request_input, list):
        try:
            input_text_tokens = count_message_tokens(request_input)
        except Exception:
            logger.exception("Failed to count text tokens for context-length debug info")
        try:
            input_serialized_tokens = count_serialized_structure_tokens(
                request_input,
                model_name=model_name,
            )
        except Exception:
            logger.exception("Failed to count structural tokens for context-length debug info")
        function_call_output_count = sum(
            1
            for item in request_input
            if isinstance(item, dict) and item.get(TYPE_KEY) == FUNCTION_CALL_OUTPUT_TYPE
        )
        if request_input:
            input_preview = str(request_input[0])[:500]
    elif request_input is not None:
        try:
            input_text_tokens = count_message_tokens(
                [{"role": USER_ROLE, CONTENT_KEY: str(request_input)}]
            )
        except Exception:
            logger.exception("Failed to count scalar input tokens for context-length debug info")
        try:
            input_serialized_tokens = count_serialized_structure_tokens(
                request_input,
                model_name=model_name,
            )
        except Exception:
            logger.exception("Failed to count scalar structural tokens for context-length debug info")
        input_preview = str(request_input)[:500]

    tools_value = params.get(REQUEST_PARAM_TOOLS)
    tool_count = len(tools_value) if isinstance(tools_value, list) else 0

    return {
        "model": params.get(REQUEST_PARAM_MODEL) or getattr(config, "MODEL", None),
        "request_class": request_class,
        "has_previous_response_id": bool(params.get(REQUEST_PREV_RESPONSE_ID)),
        "previous_response_id": params.get(REQUEST_PREV_RESPONSE_ID),
        "effective_iteration": effective_iteration,
        "tool_count": tool_count,
        "input_item_count": input_item_count,
        "function_call_output_count": function_call_output_count,
        "input_text_tokens": input_text_tokens,
        "input_serialized_tokens": input_serialized_tokens,
        "tool_schema_reserve_tokens": measured_reserves.get("tool_schema_reserve_tokens", 0),
        "structured_payload_reserve_tokens": measured_reserves.get(
            "structured_payload_reserve_tokens",
            0,
        ),
        "model_input_window": budget.get("model_input_window"),
        "usable_window": budget.get("usable_window"),
        "hidden_chain_reserve": budget.get("hidden_chain_reserve"),
        "top_level_reserve": budget.get("top_level_reserve"),
        "payload_budget": budget.get("payload_budget"),
        "decision": budget.get("decision"),
        "input_preview": input_preview,
    }


def _log_context_length_exceeded(error, params):
    """Log structured diagnostics for Responses API context-length failures.

    Args:
        error: The provider exception raised by responses.create.
        params: The request payload that triggered the failure.
    """
    model_name = None
    if isinstance(params, dict):
        model_name = params.get(REQUEST_PARAM_MODEL) or getattr(config, "MODEL", None)

    try:
        debug_info = _build_context_length_debug_info(params, model_name=model_name)
    except Exception:
        logger.exception("Failed building context-length diagnostics")
        debug_info = {
            "model": model_name,
            "request_class": classify_followup_request(params if isinstance(params, dict) else {}),
        }

    logger.error(
        "Responses API context window exceeded: model=%s request_class=%s previous_response_id=%s effective_iteration=%s tool_count=%s input_items=%s function_call_outputs=%s input_text_tokens=%s input_serialized_tokens=%s tool_schema_reserve=%s structured_payload_reserve=%s model_input_window=%s usable_window=%s hidden_chain_reserve=%s top_level_reserve=%s payload_budget=%s decision=%s error=%s",
        debug_info.get("model"),
        debug_info.get("request_class"),
        debug_info.get("previous_response_id"),
        debug_info.get("effective_iteration"),
        debug_info.get("tool_count"),
        debug_info.get("input_item_count"),
        debug_info.get("function_call_output_count"),
        debug_info.get("input_text_tokens"),
        debug_info.get("input_serialized_tokens"),
        debug_info.get("tool_schema_reserve_tokens"),
        debug_info.get("structured_payload_reserve_tokens"),
        debug_info.get("model_input_window"),
        debug_info.get("usable_window"),
        debug_info.get("hidden_chain_reserve"),
        debug_info.get("top_level_reserve"),
        debug_info.get("payload_budget"),
        debug_info.get("decision"),
        error,
    )
    logger.info(
        "Responses API context debug payload: %s",
        json.dumps(debug_info, ensure_ascii=False, default=str, sort_keys=True),
    )


def _is_context_length_exceeded_error(error):
    """Return True when an exception represents a provider context-length failure.

    Args:
        error: Exception raised by the provider client.

    Returns:
        bool: True when the exception indicates context window exhaustion.
    """
    if error is None:
        return False

    error_code = getattr(error, "code", None)
    if error_code == "context_length_exceeded":
        return True

    return "context_length_exceeded" in str(error).lower()

def configure_responses_adapter():
    """Configure the OpenAI client for Responses API usage."""
    global client
    model_name = getattr(config, "MODEL", "") or ""
    client_kwargs = {}

    if model_name.startswith(XAI_MODEL_PREFIX):
        client_kwargs["base_url"] = XAI_BASE_URL
        xai_api_key = getattr(config, "XAI_API_KEY", None) or getattr(config, "OPENAI_API_KEY", None)
        if xai_api_key:
            client_kwargs["api_key"] = xai_api_key
        logger.info("Configuring Responses adapter for xAI with model=%s", model_name)
    else:
        logger.info("Configuring Responses adapter for OpenAI with model=%s", model_name)

    client = OpenAI(**client_kwargs)

def validate_responses_config():
    """Validate that required responses API configuration is present."""
    required_configs = ["MODEL", "RESPONSES_API"]
    missing_configs = []

    for config_name in required_configs:
        if not hasattr(config, config_name) or not getattr(config, config_name):
            missing_configs.append(config_name)

    if missing_configs:
        raise ValueError(
            f"Missing required responses API configuration: {missing_configs}"
        )

    logger.debug("Responses API configuration validated successfully")

def _cancellable_responses_create(create_callable, params, progress_label=None):
    """Execute OpenAI Responses API call in a background thread, allowing Ctrl-C to cancel.

    This helper starts the provided create_callable(**params) in a daemon thread and
    temporarily sets the SIGINT handler to the default KeyboardInterrupt-raising handler
    while waiting. If the user presses Ctrl-C, a KeyboardInterrupt will be raised,
    allowing callers to handle cancellation (e.g., return control to the caller).

    Args:
        create_callable: Callable to invoke (typically client.responses.create).
        params (dict): Parameters to pass to the callable.
        progress_label (str | None): Optional label to display with progress_dots.

    Returns:
        Any: The result returned by the callable on success.

    Raises:
        KeyboardInterrupt: If the user cancels with Ctrl-C during the wait.
        Exception: Any error raised by the callable is propagated.
    """
    result_container = {"result": None, "error": None}

    def target():
        try:
            result_container["result"] = create_callable(**params)
        except Exception as e:
            result_container["error"] = e

    thread = threading.Thread(target=target, name="OpenAIResponsesCreate", daemon=True)

    # Save and set SIGINT handler to default to ensure Ctrl-C raises KeyboardInterrupt
    prev_handler = None
    try:
        try:
            prev_handler = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, signal.default_int_handler)
        except Exception:
            # If not in the main thread or setting signal fails, continue without changing handler
            prev_handler = None

        # Start the worker thread only after setting the temporary SIGINT handler
        thread.start()

        # Use progress dots while waiting
        ctx = progress_dots(progress_label) if progress_label is not None else progress_dots()
        with ctx:
            while thread.is_alive():
                thread.join(0.1)
        if result_container["error"] is not None:
            raise result_container["error"]
        return result_container["result"]
    finally:
        # Restore original SIGINT handler
        if prev_handler is not None:
            try:
                signal.signal(signal.SIGINT, prev_handler)
            except Exception:
                pass

def call_responses_api(messages, tool_descriptions, gemini_tool_descriptions, request_id=None):
    """Make the actual call to the OpenAI Responses API.

    This method supports cancellable behavior: pressing Ctrl-C during any Responses API call
    will raise KeyboardInterrupt, allowing the caller to handle cancellation (e.g., by returning
    (None, "Cancelled by user")).

    Args:
        messages (list): Prepared messages for the API
        tool_descriptions (list): Available tool specifications for the current model
        gemini_tool_descriptions (list): Alternative tool specifications (for Gemini models)

    Returns:
        dict: Normalized response wrapper suitable for convert_response_format

    Raises:
        Exception: Any API-related errors (KeyboardInterrupt will propagate for cancellation)
    """
    try:
        logger.debug("Calling responses API via OpenAI client")

        # Lazy initialize client if not already configured
        if client is None:
            try:
                configure_responses_adapter()
                logger.debug("Configured responses adapter client lazily")
            except Exception:
                logger.exception("Failed to configure responses adapter lazily")
            if client is None:
                logger.error("Responses client could not be configured. Please call configure_responses_adapter() or verify your OpenAI API credentials.")
                raise RuntimeError("Responses client could not be configured. Please call configure_responses_adapter() or verify your OpenAI API credentials.")

        resolved_model, request_model, reasoning_model, max_output_tokens = (
            _resolve_responses_turn_settings()
        )

        # Get tools for the effective turn model.
        tools, tool_choice = get_tools_for_model(
            tool_descriptions,
            gemini_tool_descriptions,
            resolved_model,
        )

        # Build request parameters, include only non-None values
        params = {REQUEST_PARAM_MODEL: request_model}

        # Determine input: if a previous response id exists, send only the new user input
        if hasattr(config, "RESPONSE_ID") and getattr(config, "RESPONSE_ID"):
            params[REQUEST_PREV_RESPONSE_ID] = getattr(config, "RESPONSE_ID")
            # Extract most recent user message content
            user_text = None
            try:
                for m in reversed(messages):
                    if isinstance(m, dict) and m.get(ROLE_KEY) == USER_ROLE:
                        user_text = m.get(CONTENT_KEY)
                        break
            except Exception:
                user_text = None
            if not user_text:
                # Fallback: concatenate all message contents
                try:
                    user_text = " ".join(
                        m.get(CONTENT_KEY, "") for m in messages if isinstance(m, dict)
                    )
                except Exception:
                    user_text = ""
            params[REQUEST_PARAM_INPUT] = user_text
            logger.debug(
                "Sending only the new user input alongside previous_response_id to OpenAI Responses API"
            )
        else:
            # First-call: send prepared messages as input (may include system preferences)
            params[REQUEST_PARAM_INPUT] = messages
            logger.debug("Sending prepared messages as input to OpenAI Responses API")

        # Add optional parameters only if present in config
        if reasoning_model:
            params[REQUEST_PARAM_TEMPERATURE] = 1
        elif getattr(config, "TEMPERATURE", None) is not None:
            params[REQUEST_PARAM_TEMPERATURE] = getattr(config, "TEMPERATURE")
        if getattr(config, "TOP_P", None) is not None:
            params[REQUEST_PARAM_TOP_P] = getattr(config, "TOP_P")
        if getattr(config, "FREQUENCY_PENALTY", None) is not None:
            params[REQUEST_PARAM_FREQUENCY_PENALTY] = getattr(config, "FREQUENCY_PENALTY")
        if getattr(config, "PRESENCE_PENALTY", None) is not None:
            params[REQUEST_PARAM_PRESENCE_PENALTY] = getattr(config, "PRESENCE_PENALTY")

        if max_output_tokens is not None:
            params[REQUEST_PARAM_MAX_OUTPUT_TOKENS] = max_output_tokens

        # Add tools if available
        if tools:
            params[REQUEST_PARAM_TOOLS] = tools
            params[REQUEST_PARAM_TOOL_CHOICE] = tool_choice
            logger.debug(
                f"Added {len(tools)} tools to responses API call with choice '{tool_choice}'"
            )
        else:
            logger.debug("No tools available for responses API call")

        # Call OpenAI Responses API (initial call) with cancellable helper
        response = _cancellable_responses_create(client.responses.create, params)

        logger.debug("Successfully received response from OpenAI Responses API")

        # Persist response id into config if present
        try:
            resp_id = getattr(response, ID_KEY, None)
            if resp_id:
                setattr(config, "RESPONSE_ID", resp_id)
                logger.debug(f"Persisted response id {resp_id} into config.RESPONSE_ID")
        except Exception:
            logger.debug("Failed to persist response id to config, continuing")

        # Extract token usage (support common shapes) for the initial response
        actual_tokens = None
        used_estimate = False
        try:
            usage = getattr(response, "usage", None)
            if usage is None:
                actual_tokens = None
                used_estimate = True
            else:
                # usage might be an object with attributes or a dict-like
                if isinstance(usage, dict):
                    actual_tokens = (
                        usage.get(USAGE_KEYS[0])
                        or usage.get(USAGE_KEYS[1])
                        or usage.get(USAGE_KEYS[2])
                    )
                else:
                    actual_tokens = (
                        getattr(usage, USAGE_KEYS[0], None)
                        or getattr(usage, USAGE_KEYS[1], None)
                        or getattr(usage, USAGE_KEYS[2], None)
                    )
                if actual_tokens is None:
                    used_estimate = True
                else:
                    used_estimate = False
            try:
                rid = getattr(response, ID_KEY, None)
            except Exception:
                rid = None
            try:
                mname = request_model
            except Exception:
                mname = None
            try:
                if isinstance(usage, dict):
                    total = usage.get("total_tokens") or usage.get("total_token_count") or usage.get("total")
                    prompt = usage.get("prompt_tokens")
                    completion = usage.get("completion_tokens")
                    input_tokens = usage.get("input_tokens")
                    output_tokens = usage.get("output_tokens")
                    reasoning_tokens = usage.get("reasoning_tokens")
                else:
                    total = getattr(usage, "total_tokens", None) or getattr(usage, "total_token_count", None) or getattr(usage, "total", None)
                    prompt = getattr(usage, "prompt_tokens", None)
                    completion = getattr(usage, "completion_tokens", None)
                    input_tokens = getattr(usage, "input_tokens", None)
                    output_tokens = getattr(usage, "output_tokens", None)
                    reasoning_tokens = getattr(usage, "reasoning_tokens", None)
            except Exception:
                total = prompt = completion = input_tokens = output_tokens = reasoning_tokens = None
            try:
                effective_prompt_tokens = prompt if prompt is not None else input_tokens
                effective_completion_tokens = completion if completion is not None else output_tokens
                effective_reasoning_tokens = reasoning_tokens
                if effective_reasoning_tokens is None:
                    details = None
                    try:
                        if isinstance(usage, dict):
                            details = usage.get("output_tokens_details")
                        else:
                            details = getattr(usage, "output_tokens_details", None)
                    except Exception:
                        details = None
                    try:
                        if isinstance(details, dict):
                            effective_reasoning_tokens = details.get("reasoning_tokens")
                        else:
                            effective_reasoning_tokens = getattr(details, "reasoning_tokens", None)
                    except Exception:
                        effective_reasoning_tokens = None
                logger.info(
                    "Responses usage model=%s id=%s total=%s prompt=%s completion=%s input=%s output=%s reasoning=%s raw=%r",
                    mname,
                    rid,
                    total,
                    effective_prompt_tokens,
                    effective_completion_tokens,
                    input_tokens,
                    output_tokens,
                    effective_reasoning_tokens,
                    usage,
                )
            except Exception:
                pass
        except Exception:
            actual_tokens = None
            used_estimate = True

        # If actual_tokens is None, set to 0 to avoid None propagation
        if actual_tokens is None:
            actual_tokens = 0

        # Update token usage and rate limiter immediately for the initial response
        try:
            update_token_usage(
                actual_tokens,
                used_estimate=used_estimate,
                response=response,
                model=resolved_model,
            )
            logger.debug(
                f"Updated token usage with {actual_tokens} tokens from OpenAI response"
            )
        except Exception:
            logger.exception("Failed to update token usage after OpenAI response")

        try:
            if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
                rate_limiter.RATE_LIMITER.add_request(actual_tokens, request_id=request_id)
                logger.debug(
                    f"Added request of {actual_tokens} tokens to rate limiter (request_id={request_id})"
                )
        except Exception:
            logger.exception("Failed to add request to rate limiter after OpenAI response")

        # Begin function/tool call handling loop (up to max iterations)
        last_response = response
        max_iterations = MAX_FUNCTION_CALL_ITERATIONS
        iteration = 0
        last_iteration_had_calls = False
        trigger_summarization_followup = False
        summarization_trigger_reason = None

        # Collect function call outputs across iterations for potential summarization and to send aggregated follow-ups.
        # We collect both the serialized follow-up items (all_function_call_outputs) that will be sent back to the Responses API
        # and a summarization-friendly representation (all_summarization_outputs) built via build_function_call_output_item.
        all_function_call_outputs = []

        while iteration < max_iterations:
            iteration += 1
            logger.debug(f"Function call handling iteration {iteration}")

            # Try to extract output items from last_response
            try:
                output = getattr(last_response, OUTPUT_KEY, None)
                if output is None:
                    try:
                        output = last_response.get(OUTPUT_KEY)  # type: ignore
                    except Exception:
                        output = None
            except Exception:
                output = None

            function_call_items = []

            # If output is a list, scan for function/tool calls
            if isinstance(output, list):
                for item in output:
                    try:
                        item_type = None
                        if hasattr(item, TYPE_KEY):
                            item_type = getattr(item, TYPE_KEY, None)
                        elif isinstance(item, dict):
                            item_type = item.get(TYPE_KEY)

                        # Normalize to string if possible
                        if item_type:
                            item_type_str = str(item_type).lower()
                        else:
                            item_type_str = None

                        if item_type_str in (FUNCTION_CALL_TYPE, TOOL_CALL_TYPE):
                            logger.debug(
                                f"Detected function/tool call item with type '{item_type_str}'"
                            )

                            # Extract call id
                            call_id = None
                            if hasattr(item, CALL_ID_KEYS[0]):
                                call_id = getattr(item, CALL_ID_KEYS[0], None)
                            elif hasattr(item, CALL_ID_KEYS[1]):
                                call_id = getattr(item, CALL_ID_KEYS[1], None)
                            elif isinstance(item, dict):
                                call_id = item.get(CALL_ID_KEYS[0]) or item.get(CALL_ID_KEYS[1])

                            # Extract function/tool name
                            name = None
                            if hasattr(item, NAME_KEY):
                                name = getattr(item, NAME_KEY, None)
                            elif isinstance(item, dict):
                                name = item.get(NAME_KEY)

                            # Sometimes the tool name might be under 'tool' or 'tool_name'
                            if not name and isinstance(item, dict):
                                for tk in TOOL_NAME_KEYS:
                                    if tk in item:
                                        name = item.get(tk)
                                        break
                            if not name and hasattr(item, TOOL_NAME_KEYS[0]):
                                name = getattr(item, TOOL_NAME_KEYS[0], None)

                            # Extract arguments; can be dict, object, or JSON string
                            arguments = None
                            if hasattr(item, ARGUMENTS_KEY):
                                try:
                                    arguments = getattr(item, ARGUMENTS_KEY, None)
                                except Exception:
                                    arguments = None
                            elif isinstance(item, dict):
                                arguments = (
                                    item.get(ARGUMENTS_KEY)
                                    or item.get(CONTENT_KEY)
                                    or item.get(ARGS_KEY)
                                )

                            # If arguments is a string, attempt to parse JSON
                            if isinstance(arguments, str):
                                try:
                                    parsed_args = json.loads(arguments)
                                    arguments = parsed_args
                                except Exception:
                                    # keep as string if not JSON
                                    pass

                            # Build normalized function call item
                            function_call_items.append(
                                {
                                    "call_id": call_id,
                                    "name": name,
                                    "arguments": arguments,
                                    "raw_item": item,
                                }
                            )
                    except Exception:
                        logger.exception(
                            "Error while scanning output items for function calls"
                        )

            # Track whether this iteration had any function/tool calls
            last_iteration_had_calls = bool(function_call_items)

            # If no function calls detected, break the loop
            if not function_call_items:
                logger.debug(
                    "No function/tool call items detected in response output; exiting function call loop"
                )
                break

            # Execute each detected function call
            function_call_outputs = []
            for fc in function_call_items:
                call_id = fc.get("call_id")
                name = fc.get("name")
                arguments = fc.get("arguments")

                logger.debug(
                    f"Preparing to execute tool/function '{name}' with call_id '{call_id}' and arguments: {arguments}"
                )

                tool_call = {
                    "function": {"name": name, "arguments": arguments},
                    "id": call_id,
                }

                try:
                    result, error = execute_tool_call(tool_call)
                    if error:
                        logger.error(
                            f"Error executing tool/function '{name}' (call_id: {call_id}): {error}"
                        )
                        result_or_error = {"error": str(error)}
                    else:
                        logger.debug(
                            f"Executed tool/function '{name}' (call_id: {call_id}) successfully"
                        )
                        result_or_error = result if result is not None else {}
                except Exception as e:
                    logger.exception(
                        f"Exception executing tool/function '{name}' (call_id: {call_id})"
                    )
                    result_or_error = {"error": str(e)}
                    _maybe_escalate_reasoning_on_tool_failure(None, str(e))
                else:
                    _maybe_escalate_reasoning_on_tool_failure(result, error)

                try:
                    output_payload = serialize_tool_output(result_or_error)
                except Exception:
                    try:
                        output_payload = serialize_tool_output(
                            {"error": "Unable to serialize tool result"}
                        )
                    except Exception:
                        output_payload = SERIALIZATION_FAILED_STR

                # Truncate serialized output to configured per-tool token limit to avoid oversized follow-ups.
                try:
                    _, current_request_model, _, _ = _resolve_responses_turn_settings()
                    token_limit = int(config.TOOL_OUTPUT_TOKEN_LIMIT)
                    truncated_output = truncate_to_token_limit(
                        output_payload, token_limit, model=current_request_model
                    )
                except Exception:
                    # If truncation fails for any reason, fall back to the original serialized payload.
                    logger.exception("Failed to truncate tool output; using full serialized output")
                    truncated_output = output_payload

                item = {
                    TYPE_KEY: FUNCTION_CALL_OUTPUT_TYPE,
                    "call_id": call_id,
                    "output": truncated_output,
                }

                function_call_outputs.append(item)

                # Also collect across iterations:
                # - append the serialized follow-up item that will be sent back to the Responses API
                # - append a summarization-friendly representation via build_function_call_output_item
                try:
                    try:
                        summary_item = build_function_call_output_item(call_id, result_or_error, serialized_output=truncated_output)
                        try:
                            summary_item['parent_response_id'] = getattr(last_response, ID_KEY, None)
                        except Exception:
                            # If setting parent_response_id fails, proceed without it
                            pass
                        all_function_call_outputs.append(summary_item)
                    except Exception:
                        # If build_function_call_output_item itself fails, attempt to append a minimal structure
                        minimal = {"id": call_id, "result": result_or_error}
                        try:
                            minimal['parent_response_id'] = getattr(last_response, ID_KEY, None)
                        except Exception:
                            pass
                        all_function_call_outputs.append(minimal)
                except Exception:
                    logger.exception("Failed to append to all_function_call_outputs")

                # Summarization item omitted.

            # If we have outputs from executing tools, send them back as a follow-up response
            if function_call_outputs:
                try:
                    (
                        followup_resolved_model,
                        followup_request_model,
                        followup_reasoning_model,
                        followup_max_output_tokens,
                    ) = _resolve_responses_turn_settings()
                    followup_tools, followup_tool_choice = get_tools_for_model(
                        tool_descriptions,
                        gemini_tool_descriptions,
                        followup_resolved_model,
                    )
                    followup_params = {REQUEST_PARAM_MODEL: followup_request_model}
                    # Ensure previous_response_id is the last persisted response id
                    if hasattr(config, "RESPONSE_ID") and getattr(config, "RESPONSE_ID"):
                        followup_params[REQUEST_PREV_RESPONSE_ID] = getattr(config, "RESPONSE_ID")
                    followup_params[REQUEST_PARAM_INPUT] = function_call_outputs

                    # Preserve optional params
                    if followup_reasoning_model:
                        followup_params[REQUEST_PARAM_TEMPERATURE] = 1
                    elif getattr(config, "TEMPERATURE", None) is not None:
                        followup_params[REQUEST_PARAM_TEMPERATURE] = getattr(config, "TEMPERATURE")
                    if getattr(config, "TOP_P", None) is not None:
                        followup_params[REQUEST_PARAM_TOP_P] = getattr(config, "TOP_P")
                    if getattr(config, "FREQUENCY_PENALTY", None) is not None:
                        followup_params[REQUEST_PARAM_FREQUENCY_PENALTY] = getattr(
                            config, "FREQUENCY_PENALTY"
                        )
                    if getattr(config, "PRESENCE_PENALTY", None) is not None:
                        followup_params[REQUEST_PARAM_PRESENCE_PENALTY] = getattr(
                            config, "PRESENCE_PENALTY"
                        )
                    if followup_max_output_tokens is not None:
                        followup_params[REQUEST_PARAM_MAX_OUTPUT_TOKENS] = followup_max_output_tokens

                    # Add tools if available
                    if followup_tools:
                        followup_params[REQUEST_PARAM_TOOLS] = followup_tools
                        followup_params[REQUEST_PARAM_TOOL_CHOICE] = followup_tool_choice

                    logger.debug(
                        f"Sending follow-up responses.create with {len(function_call_outputs)} function_call_output items"
                    )

                    input_window = _resolve_model_input_window()
                    budget_iteration = iteration + 1
                    if _get_followup_tool_omission_hints_enabled():
                        logger.info(
                            "Follow-up tool omission hints are enabled, but no omission classifier is wired yet; keeping tools enabled."
                        )
                    budgeted_followup_params, followup_budget = budget_followup_request(
                        followup_params,
                        iteration=budget_iteration,
                        input_window=input_window,
                    )
                    followup_params = budgeted_followup_params

                    try:
                        followup_input = followup_params.get(REQUEST_PARAM_INPUT)
                        original_followup_tokens = (
                            count_message_tokens(followup_input)
                            if isinstance(followup_input, list)
                            else None
                        )
                        payload_budget = followup_budget.get("payload_budget")
                        budget_decision = followup_budget.get("decision")
                        final_followup_tokens = original_followup_tokens

                        if (
                            isinstance(payload_budget, int)
                            and payload_budget > 0
                            and isinstance(followup_input, list)
                            and isinstance(original_followup_tokens, int)
                            and original_followup_tokens > payload_budget
                        ):
                            followup_params = token_budgeter(
                                followup_params,
                                input_window=payload_budget,
                                model_name=followup_resolved_model,
                            )
                            followup_input = followup_params.get(REQUEST_PARAM_INPUT)
                            if isinstance(followup_input, list):
                                final_followup_tokens = count_message_tokens(followup_input)
                                if (
                                    isinstance(final_followup_tokens, int)
                                    and final_followup_tokens <= payload_budget
                                ):
                                    budget_decision = FOLLOWUP_BUDGET_DECISION_SEND_TRIMMED
                                else:
                                    budget_decision = FOLLOWUP_BUDGET_DECISION_FALLBACK

                        logger.info(
                            "Follow-up budget preflight: class=%s input_window=%s usable_window=%s hidden_chain_reserve=%s tool_schema_reserve=%s structured_payload_reserve=%s top_level_reserve=%s payload_budget=%s original_input_estimate=%s final_input_estimate=%s decision=%s",
                            followup_budget.get("request_class"),
                            followup_budget.get("model_input_window"),
                            followup_budget.get("usable_window"),
                            followup_budget.get("hidden_chain_reserve"),
                            followup_budget.get("tool_schema_reserve"),
                            followup_budget.get("structured_payload_reserve"),
                            followup_budget.get("top_level_reserve"),
                            payload_budget,
                            original_followup_tokens,
                            final_followup_tokens,
                            budget_decision,
                        )

                        if budget_decision == FOLLOWUP_BUDGET_DECISION_UNKNOWN:
                            logger.warning(
                                "Routing chained follow-up into summarization/rebase fallback because the retained provider-side context cannot be measured locally (previous_response_id=%s, input_type=%s)",
                                followup_params.get(REQUEST_PREV_RESPONSE_ID),
                                type(followup_input).__name__,
                            )
                            if _get_followup_show_recovery_notices():
                                print(
                                    "[notice] I’m condensing context to keep this thread reliable."
                                )
                            trigger_summarization_followup = True
                            summarization_trigger_reason = "unknown chained follow-up budget"
                            break
                        elif budget_decision == FOLLOWUP_BUDGET_DECISION_FALLBACK:
                            logger.warning(
                                "Routing tool-result follow-up into summarization/rebase fallback because the reserve-aware payload budget could not safely admit the request (payload_budget=%s, final_input_estimate=%s)",
                                payload_budget,
                                final_followup_tokens,
                            )
                            if _get_followup_show_recovery_notices():
                                print(
                                    "[notice] I’m condensing context to keep this thread reliable."
                                )
                            trigger_summarization_followup = True
                            summarization_trigger_reason = "reserve-aware payload fallback"
                            break
                    except Exception:
                        logger.exception("Failed during reserve-aware follow-up budgeting preflight")

                    # H2: Preflight rate-limit gate for tool-call follow-up.
                    # Previously, follow-up responses.create calls only recorded
                    # tokens post-hoc, allowing a tool loop to burst past the
                    # configured TPM before any cooldown fired.
                    try:
                        if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
                            try:
                                followup_input = followup_params.get(REQUEST_PARAM_INPUT)
                                if isinstance(followup_input, list):
                                    preflight_tokens = count_message_tokens(followup_input)
                                else:
                                    preflight_tokens = count_message_tokens(
                                        [{"role": "user", "content": str(followup_input or "")}]
                                    )
                            except Exception:
                                logger.exception(
                                    "Failed to estimate follow-up payload tokens for rate-limit preflight; using 0"
                                )
                                preflight_tokens = 0
                            wait_result = rate_limiter.RATE_LIMITER.wait_if_needed(preflight_tokens)
                            if wait_result is None:
                                logger.warning(
                                    "Skipping follow-up responses.create: estimated tokens (%s) exceed rate-limiter safety threshold",
                                    preflight_tokens,
                                )
                                break
                    except Exception:
                        logger.exception(
                            "Rate-limit preflight check failed for follow-up responses.create; proceeding without gating"
                        )

                    # Follow-up call with cancellable helper
                    followup_response = _cancellable_responses_create(client.responses.create, followup_params)

                    logger.debug("Received follow-up response from OpenAI Responses API")

                    # Persist follow-up response id
                    try:
                        follow_id = getattr(followup_response, ID_KEY, None)
                        if follow_id:
                            setattr(config, "RESPONSE_ID", follow_id)
                            logger.debug(
                                f"Persisted follow-up response id {follow_id} into config.RESPONSE_ID"
                            )
                    except Exception:
                        logger.debug("Failed to persist follow-up response id to config, continuing")

                    # Extract token usage for follow-up response
                    follow_tokens = None
                    follow_used_estimate = False
                    try:
                        usage = getattr(followup_response, "usage", None)
                        if usage is None:
                            follow_tokens = None
                            follow_used_estimate = True
                        else:
                            if isinstance(usage, dict):
                                follow_tokens = (
                                    usage.get(USAGE_KEYS[0])
                                    or usage.get(USAGE_KEYS[1])
                                    or usage.get(USAGE_KEYS[2])
                                )
                            else:
                                follow_tokens = (
                                    getattr(usage, USAGE_KEYS[0], None)
                                    or getattr(usage, USAGE_KEYS[1], None)
                                    or getattr(usage, USAGE_KEYS[2], None)
                                )
                            if follow_tokens is None:
                                follow_used_estimate = True
                            else:
                                follow_used_estimate = False
                    except Exception:
                        follow_tokens = None
                        follow_used_estimate = True

                    if follow_tokens is None:
                        follow_tokens = 0

                    # Update token usage and rate limiter for follow-up
                    try:
                        update_token_usage(
                            follow_tokens,
                            used_estimate=follow_used_estimate,
                            response=followup_response,
                            model=followup_resolved_model,
                        )
                        logger.debug(
                            f"Updated token usage with {follow_tokens} tokens from follow-up OpenAI response"
                        )
                    except Exception:
                        logger.exception(
                            "Failed to update token usage after follow-up OpenAI response"
                        )

                    try:
                        if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
                            rate_limiter.RATE_LIMITER.add_request(follow_tokens)
                            logger.debug(
                                f"Added follow-up request of {follow_tokens} tokens to rate limiter"
                            )
                    except Exception:
                        logger.exception(
                            "Failed to add follow-up request to rate limiter after OpenAI response"
                        )

                    # Safely add follow_tokens to actual_tokens so total token accounting includes the follow-up
                    try:
                        if actual_tokens is None:
                            actual_tokens = 0
                        try:
                            # Attempt numeric addition; coerce to int if possible
                            if isinstance(follow_tokens, (int, float)):
                                actual_tokens += int(follow_tokens)
                                logger.debug(
                                    f"Added {follow_tokens} follow-up tokens to actual_tokens, new total: {actual_tokens}"
                                )
                            else:
                                # Try to coerce strings that represent integers
                                if isinstance(follow_tokens, str) and follow_tokens.isdigit():
                                    actual_tokens += int(follow_tokens)
                                    logger.debug(
                                        f"Coerced and added follow-up tokens '{follow_tokens}' to actual_tokens, new total: {actual_tokens}"
                                    )
                                else:
                                    logger.debug(
                                        f"Follow-up tokens value not numeric, skipping addition to actual_tokens: {follow_tokens}"
                                    )
                        except Exception:
                            logger.exception("Failed while attempting to coerce and add follow_tokens to actual_tokens")
                    except Exception:
                        logger.exception("Failed to add follow_tokens to actual_tokens")

                    # Set last_response to followup_response and continue loop
                    last_response = followup_response
                except Exception as error:
                    if _is_context_length_exceeded_error(error):
                        logger.warning(
                            "Follow-up responses.create exceeded the provider context window while reusing previous_response_id=%s; retrying with a fresh request chain",
                            getattr(config, "RESPONSE_ID", None),
                        )
                        try:
                            setattr(config, "RESPONSE_ID", None)
                            logger.warning(
                                "Cleared config.RESPONSE_ID after oversized tool follow-up so the next retry starts a fresh response chain"
                            )
                        except Exception:
                            logger.exception(
                                "Failed to clear config.RESPONSE_ID after oversized tool follow-up"
                            )
                        logger.info(
                            "Retrying the turn as a fresh request after tool follow-up context exhaustion"
                        )
                        return call_responses_api(
                            messages,
                            tool_descriptions,
                            gemini_tool_descriptions,
                            request_id=request_id,
                        )

                    logger.exception(
                        "Failed to send follow-up responses.create for function call outputs"
                    )
                    try:
                        setattr(config, "RESPONSE_ID", None)
                        logger.warning(
                            "Cleared config.RESPONSE_ID after failed tool follow-up to avoid reusing a broken response chain"
                        )
                    except Exception:
                        logger.exception(
                            "Failed to clear config.RESPONSE_ID after tool follow-up failure"
                        )
                    raise
            else:
                # No outputs to send back; break loop
                break

        # If we reached the max iteration limit and the last iteration had function/tool calls,
        # attempt to send a summarization follow-up to avoid truncation of tool call results.
        try:
            if (
                ((iteration >= max_iterations and last_iteration_had_calls) or trigger_summarization_followup)
                and all_function_call_outputs
            ):
                if client is None:
                    logger.debug("Skipping summarization follow-up because client is not configured")
                elif not (hasattr(config, "RESPONSE_ID") and getattr(config, "RESPONSE_ID")):
                    logger.debug("Skipping summarization follow-up because no config.RESPONSE_ID is present")
                else:
                    try:
                        (
                            summary_resolved_model,
                            summary_request_model,
                            _summary_reasoning_model,
                            _summary_max_output_tokens,
                        ) = _resolve_responses_turn_settings()

                        # Build a summary instruction that explicitly prevents further tool usage.
                        # NOTE: We intentionally do NOT include tools in the summarization follow-up
                        # parameters to prevent the model from issuing additional tool/function calls.
                        summary_instruction = (
                            "Please summarize the previous response and the results of the function/tool calls into a concise summary. "
                            "Do NOT call any tools or request further function executions. Only provide a brief summary of the outputs."
                        )

                        # Compute summary token allotment; preserve previous behavior
                        try:
                            model_window = int(getattr(config, "MODEL_OUTPUT_WINDOW"))
                            computed_summary_tokens = max(
                                int(SUMMARY_MAX_OUTPUT_TOKENS // 2),
                                min(int(model_window * 0.08), int(SUMMARY_MAX_OUTPUT_TOKENS))
                            )
                        except Exception:
                            computed_summary_tokens = int(SUMMARY_MAX_OUTPUT_TOKENS)

                        logger.debug(
                            f"[SUMMARIZATION] Using SUMMARY_MAX_OUTPUT_TOKENS={computed_summary_tokens} "
                            f"(MODEL_OUTPUT_WINDOW={getattr(config, 'MODEL_OUTPUT_WINDOW', 'n/a')})"
                        )

                        # Build summarization follow-up input: include all aggregated function_call outputs
                        # collected across iterations, followed by the explicit summary instruction that tells
                        # the model NOT to call any tools. Intentionally omit REQUEST_PARAM_TOOLS here.
                        try:
                            # Compute parent_response_id by scanning aggregated function outputs for the first non-empty parent_response_id
                            parent_resp_id = None
                            try:
                                for fo in all_function_call_outputs:
                                    try:
                                        if isinstance(fo, dict):
                                            pr = fo.get("parent_response_id")
                                            if pr:
                                                parent_resp_id = pr
                                                break
                                    except Exception:
                                        continue
                            except Exception:
                                parent_resp_id = None
                            if parent_resp_id is None:
                                parent_resp_id = getattr(config, "RESPONSE_ID")

                            # Use build_summarization_followup_params to obtain sanitized parameters and mapping
                            sfp = build_summarization_followup_params(
                                prev_response_id=parent_resp_id,
                                function_call_outputs=all_function_call_outputs,
                                summary_instruction=summary_instruction,
                                model=summary_resolved_model,
                                max_output_tokens=computed_summary_tokens,
                            )

                            # Map sanitized helper output into API parameter names, ensure instruction appended after outputs
                            summary_params = {}

                            # model -> REQUEST_PARAM_MODEL: use returned sfp['model'] if present, else fallback
                            try:
                                if isinstance(sfp, dict) and sfp.get("model"):
                                    summary_params[REQUEST_PARAM_MODEL] = strip_openai_prefix(sfp.get("model"))
                                else:
                                    summary_params[REQUEST_PARAM_MODEL] = summary_request_model
                            except Exception:
                                summary_params[REQUEST_PARAM_MODEL] = summary_request_model

                            # previous_response_id -> REQUEST_PREV_RESPONSE_ID: only reuse an existing
                            # provider chain when summarizing tool follow-up payloads. For chained
                            # user-followups that already exceeded local measurability, force a fresh
                            # summarization request so the provider does not re-include the oversized
                            # retained chain we are trying to compact away.
                            try:
                                if summarization_trigger_reason == "unknown chained follow-up budget" and followup_budget.get("request_class") == FOLLOWUP_REQUEST_CLASS_CHAINED:
                                    summary_params[REQUEST_PREV_RESPONSE_ID] = None
                                elif isinstance(sfp, dict) and (sfp.get("prev_response_id") or sfp.get("parent_response_id")):
                                    summary_params[REQUEST_PREV_RESPONSE_ID] = sfp.get("prev_response_id") or sfp.get("parent_response_id")
                                else:
                                    summary_params[REQUEST_PREV_RESPONSE_ID] = getattr(config, "RESPONSE_ID")
                            except Exception:
                                summary_params[REQUEST_PREV_RESPONSE_ID] = getattr(config, "RESPONSE_ID")

                            # function_call_outputs -> REQUEST_PARAM_INPUT (as list), then append explicit typed instruction
                            try:
                                func_outputs = list(sfp.get("function_call_outputs") or []) if isinstance(sfp, dict) else list(all_function_call_outputs)
                            except Exception:
                                func_outputs = list(all_function_call_outputs)

                            # Convert aggregated function outputs into role/content assistant messages for summarization follow-up
                            try:
                                summary_input_messages = []
                                # We'll also build typed function_call_output items to include in the API payload
                                typed_function_call_items = []
                                for fo in func_outputs:
                                    try:
                                        # If item is a dict, extract call id and output field robustly
                                        if isinstance(fo, dict):
                                            call_id = None
                                            # Prefer 'id' then 'call_id'
                                            try:
                                                call_id = fo.get("id") or fo.get("call_id")
                                            except Exception:
                                                call_id = None

                                            # Attempt to find output string in common locations
                                            out_val = None
                                            try:
                                                # Preferentially use output, then serialized_output, result, text, content, else entire item
                                                try:
                                                    out_val = fo.get("output") or fo.get("serialized_output") or fo.get("result") or fo.get("text") or fo.get("content") or fo
                                                except Exception:
                                                    out_val = fo
                                            except Exception:
                                                out_val = fo

                                            # Check parent_response_id filtering: only include items whose parent_response_id == parent_resp_id (if parent_response_id is present)
                                            try:
                                                fo_parent = fo.get("parent_response_id") if isinstance(fo, dict) else None
                                            except Exception:
                                                fo_parent = None
                                            try:
                                                if fo_parent is not None and parent_resp_id is not None and fo_parent != parent_resp_id:
                                                    logger.debug(f"Skipping function output with call_id={call_id} due to parent_response_id mismatch: {fo_parent} != {parent_resp_id}")
                                                    continue
                                            except Exception:
                                                # If checking fails, proceed to include item
                                                pass

                                            # Coerce out_val to string safely for assistant-facing message
                                            if isinstance(out_val, (dict, list)):
                                                try:
                                                    out_str = json.dumps(out_val)
                                                except Exception:
                                                    out_str = str(out_val)
                                            else:
                                                try:
                                                    out_str = str(out_val)
                                                except Exception:
                                                    out_str = ""

                                            # Build typed function_call_output item to include in the API input
                                            try:
                                                typed_item = { TYPE_KEY: FUNCTION_CALL_OUTPUT_TYPE, "call_id": call_id, "output": out_str }
                                                typed_function_call_items.append(typed_item)
                                            except Exception:
                                                # fallback to minimal typed item
                                                try:
                                                    typed_function_call_items.append({ TYPE_KEY: FUNCTION_CALL_OUTPUT_TYPE, "call_id": call_id, "output": out_str })
                                                except Exception:
                                                    pass

                                            if call_id:
                                                content = f"Function call {call_id}: {out_str}"
                                            else:
                                                content = out_str

                                            summary_input_messages.append({ "role": "assistant", "content": content })
                                        else:
                                            # Non-dict items: coerce to string
                                            s = str(fo)
                                            # Also include typed item for non-dict as best-effort
                                            try:
                                                typed_function_call_items.append({ TYPE_KEY: FUNCTION_CALL_OUTPUT_TYPE, "call_id": None, "output": s })
                                            except Exception:
                                                pass
                                            summary_input_messages.append({ "role": "assistant", "content": s })
                                    except Exception:
                                        logger.exception("Failed converting a function output item to assistant message for summarization")
                                        raise

                                # Append the explicit user instruction as the last message
                                try:
                                    summary_input_messages.append({"role": USER_ROLE, "content": summary_instruction})
                                except Exception:
                                    summary_input_messages.append({"role": USER_ROLE, "content": summary_instruction})

                                # Combine typed items and assistant messages into final API input payload: typed items first, then assistant messages/instruction.
                                try:
                                    combined_input = []
                                    # Add typed items first
                                    combined_input.extend(typed_function_call_items)
                                    # Then append assistant messages
                                    combined_input.extend(summary_input_messages)
                                    summary_params[REQUEST_PARAM_INPUT] = combined_input
                                except Exception:
                                    # If combining fails, fall back to assistant messages only
                                    summary_params[REQUEST_PARAM_INPUT] = summary_input_messages

                                # Estimate tokens for the assembled input for logging: convert typed items to assistant messages for estimation
                                try:
                                    estimation_messages = []
                                    # Convert typed items into assistant messages for estimation
                                    for t in typed_function_call_items:
                                        try:
                                            cid = t.get("call_id")
                                            out = t.get("output")
                                            out_str = ""
                                            if isinstance(out, (dict, list)):
                                                try:
                                                    out_str = json.dumps(out)
                                                except Exception:
                                                    out_str = str(out)
                                            else:
                                                out_str = str(out) if out is not None else ""
                                            if cid:
                                                estimation_messages.append({"role": "assistant", "content": f"Function call {cid}: {out_str}"})
                                            else:
                                                estimation_messages.append({"role": "assistant", "content": out_str})
                                        except Exception:
                                            continue
                                    # Append assistant messages (including the final user instruction) to estimation messages
                                    try:
                                        for m in summary_input_messages:
                                            if isinstance(m, dict) and m.get("role") and m.get("content") is not None:
                                                estimation_messages.append(m)
                                            else:
                                                estimation_messages.append({"role": "assistant", "content": str(m)})
                                    except Exception:
                                        pass
                                    try:
                                        estimated_summary_tokens = estimate_response_tokens(estimation_messages)
                                        logger.debug(f"Estimated tokens for summarization follow-up input: {estimated_summary_tokens}")
                                    except Exception:
                                        logger.debug("Failed to estimate tokens for summarization follow-up input")
                                except Exception:
                                    logger.debug("Failed to build estimation messages for summarization follow-up")
                            except Exception:
                                # If conversion fails, log and fall back to sending only the summary instruction
                                logger.exception("Failed to build summary_input_messages from function outputs; falling back to instruction-only summarization")
                                summary_params[REQUEST_PARAM_INPUT] = [{"role": USER_ROLE, "content": summary_instruction}]
                            # max_output_tokens -> REQUEST_PARAM_MAX_OUTPUT_TOKENS
                            try:
                                if isinstance(sfp, dict) and sfp.get("max_output_tokens") is not None:
                                    summary_params[REQUEST_PARAM_MAX_OUTPUT_TOKENS] = sfp.get("max_output_tokens")
                                else:
                                    summary_params[REQUEST_PARAM_MAX_OUTPUT_TOKENS] = computed_summary_tokens
                            except Exception:
                                summary_params[REQUEST_PARAM_MAX_OUTPUT_TOKENS] = computed_summary_tokens

                        except Exception:
                            # Fallback: if building summary_inputs fails, revert to simple instruction-only summarization
                            try:
                                summary_inputs = list(all_function_call_outputs)
                                # Convert fallback summary_inputs into assistant messages
                                try:
                                    summary_input_messages = []
                                    typed_function_call_items = []
                                    for fo in summary_inputs:
                                        try:
                                            if isinstance(fo, dict):
                                                call_id = fo.get("id") or fo.get("call_id")
                                                out_val = fo.get("output") if fo.get("output") is not None else fo
                                                if isinstance(out_val, (dict, list)):
                                                    try:
                                                        out_str = json.dumps(out_val)
                                                    except Exception:
                                                        out_str = str(out_val)
                                                else:
                                                    out_str = str(out_val)
                                                # Build typed item
                                                try:
                                                    typed_function_call_items.append({ TYPE_KEY: FUNCTION_CALL_OUTPUT_TYPE, "call_id": call_id, "output": out_str })
                                                except Exception:
                                                    pass
                                                if call_id:
                                                    content = f"Function call {call_id}: {out_str}"
                                                else:
                                                    content = out_str
                                                summary_input_messages.append({"role": "assistant", "content": content})
                                            else:
                                                s = str(fo)
                                                try:
                                                    typed_function_call_items.append({ TYPE_KEY: FUNCTION_CALL_OUTPUT_TYPE, "call_id": None, "output": s })
                                                except Exception:
                                                    pass
                                                summary_input_messages.append({"role": "assistant", "content": s})
                                        except Exception:
                                            logger.exception("Failed converting a fallback function output item to assistant message for summarization")
                                            raise
                                    # Append the summary instruction
                                    summary_input_messages.append({"role": USER_ROLE, "content": summary_instruction})
                                    # Combine typed items and assistant messages
                                    try:
                                        combined_input = []
                                        combined_input.extend(typed_function_call_items)
                                        combined_input.extend(summary_input_messages)
                                        summary_params = {
                                            REQUEST_PARAM_MODEL: summary_request_model,
                                            REQUEST_PREV_RESPONSE_ID: getattr(config, "RESPONSE_ID"),
                                            REQUEST_PARAM_INPUT: combined_input,
                                            REQUEST_PARAM_MAX_OUTPUT_TOKENS: computed_summary_tokens,
                                        }
                                    except Exception:
                                        summary_params = {
                                            REQUEST_PARAM_MODEL: summary_request_model,
                                            REQUEST_PREV_RESPONSE_ID: getattr(config, "RESPONSE_ID"),
                                            REQUEST_PARAM_INPUT: summary_input_messages,
                                            REQUEST_PARAM_MAX_OUTPUT_TOKENS: computed_summary_tokens,
                                        }
                                    # Estimate tokens for fallback assembled input
                                    try:
                                        estimation_messages = []
                                        for t in typed_function_call_items:
                                            try:
                                                cid = t.get("call_id")
                                                out = t.get("output")
                                                out_str = ""
                                                if isinstance(out, (dict, list)):
                                                    try:
                                                        out_str = json.dumps(out)
                                                    except Exception:
                                                        out_str = str(out)
                                                else:
                                                    out_str = str(out) if out is not None else ""
                                                if cid:
                                                    estimation_messages.append({"role": "assistant", "content": f"Function call {cid}: {out_str}"})
                                                else:
                                                    estimation_messages.append({"role": "assistant", "content": out_str})
                                            except Exception:
                                                continue
                                        for m in summary_input_messages:
                                            if isinstance(m, dict) and m.get("content") is not None:
                                                estimation_messages.append(m)
                                            else:
                                                estimation_messages.append({"role": "assistant", "content": str(m)})
                                        try:
                                            estimated_summary_tokens = estimate_response_tokens(estimation_messages)
                                            logger.debug(f"Estimated tokens for summarization follow-up input (fallback): {estimated_summary_tokens}")
                                        except Exception:
                                            logger.debug("Failed to estimate tokens for summarization follow-up input (fallback)")
                                    except Exception:
                                        logger.debug("Failed to build estimation messages for summarization follow-up (fallback)")
                                except Exception:
                                    logger.exception("Failed to build summary_input_messages in fallback; using instruction-only payload")
                                    summary_params = {
                                        REQUEST_PARAM_MODEL: summary_request_model,
                                        REQUEST_PREV_RESPONSE_ID: getattr(config, "RESPONSE_ID"),
                                        REQUEST_PARAM_INPUT: {"role": USER_ROLE, "content": summary_instruction},
                                        REQUEST_PARAM_MAX_OUTPUT_TOKENS: computed_summary_tokens,
                                    }
                            except Exception:
                                summary_params = {
                                    REQUEST_PARAM_MODEL: summary_request_model,
                                    REQUEST_PREV_RESPONSE_ID: getattr(config, "RESPONSE_ID"),
                                    REQUEST_PARAM_INPUT: {"role": USER_ROLE, "content": summary_instruction},
                                    REQUEST_PARAM_MAX_OUTPUT_TOKENS: computed_summary_tokens,
                                }

                        # Before sending summarization follow-up, log a visible warning with the prev_response_id to be used and call IDs included.
                        try:
                            try:
                                # Determine prev_response_id to be used for logging
                                prev_id_for_logging = None
                                if isinstance(sfp, dict) and (sfp.get("prev_response_id") or sfp.get("parent_response_id")):
                                    prev_id_for_logging = sfp.get("prev_response_id") or sfp.get("parent_response_id")
                                else:
                                    prev_id_for_logging = parent_resp_id if 'parent_resp_id' in locals() else getattr(config, "RESPONSE_ID")
                            except Exception:
                                prev_id_for_logging = getattr(config, "RESPONSE_ID")

                            # Collect call_ids from typed_function_call_items if present, else from func_outputs
                            call_ids = []
                            try:
                                if 'typed_function_call_items' in locals() and isinstance(typed_function_call_items, list) and typed_function_call_items:
                                    for t in typed_function_call_items:
                                        try:
                                            if isinstance(t, dict):
                                                cid = t.get("call_id")
                                                call_ids.append(cid)
                                        except Exception:
                                            continue
                                else:
                                    # fallback: extract from func_outputs
                                    if isinstance(func_outputs, list):
                                        for fo in func_outputs:
                                            try:
                                                if isinstance(fo, dict):
                                                    cid = fo.get("call_id") or fo.get("id")
                                                    call_ids.append(cid)
                                            except Exception:
                                                continue
                            except Exception:
                                call_ids = []

                            logger.info("Summarization follow-up will use previous_response_id=%s and include call_ids=%s", prev_id_for_logging, call_ids)
                        except Exception:
                            logger.exception("Failed to log summarization follow-up warning")

                        trigger_reason = (
                            summarization_trigger_reason
                            or "function call iteration truncation"
                        )
                        logger.debug(
                            "Sending summarization follow-up due to %s",
                            trigger_reason,
                        )
                        if _get_followup_show_recovery_notices():
                            print(
                                "[notice] I’m continuing from a condensed summary to avoid context overflow."
                            )
                        # Pre-send estimation/logging step for summarization payload
                        try:
                            try:
                                est_input = summary_params.get(REQUEST_PARAM_INPUT)
                            except Exception:
                                est_input = summary_params.get(REQUEST_PARAM_INPUT) if isinstance(summary_params, dict) else None
                            estimation_messages = []
                            if isinstance(est_input, list):
                                for itm in est_input:
                                    try:
                                        if isinstance(itm, dict):
                                            # Typed function_call_output item
                                            if itm.get(TYPE_KEY) == FUNCTION_CALL_OUTPUT_TYPE:
                                                cid = itm.get("call_id")
                                                out_val = itm.get("output") or itm.get("serialized_output") or itm.get("result") or itm.get("text") or itm.get("content") or itm
                                                if isinstance(out_val, (dict, list)):
                                                    try:
                                                        out_str = json.dumps(out_val)
                                                    except Exception:
                                                        out_str = str(out_val)
                                                else:
                                                    out_str = str(out_val) if out_val is not None else ""
                                                if cid:
                                                    estimation_messages.append({"role": "assistant", "content": f"Function call {cid}: {out_str}"})
                                                else:
                                                    estimation_messages.append({"role": "assistant", "content": out_str})
                                            # Already structured message with role/content
                                            elif itm.get("role") and itm.get("content") is not None:
                                                estimation_messages.append({"role": itm.get("role"), "content": itm.get("content")})
                                            else:
                                                # Fallback: stringify
                                                try:
                                                    s = json.dumps(itm) if not isinstance(itm, str) else itm
                                                except Exception:
                                                    s = str(itm)
                                                estimation_messages.append({"role": "assistant", "content": s})
                                        else:
                                            # Non-dict -> coerce to assistant message
                                            estimation_messages.append({"role": "assistant", "content": str(itm)})
                                    except Exception:
                                        continue
                            elif isinstance(est_input, dict):
                                if est_input.get("role") and est_input.get("content") is not None:
                                    estimation_messages.append({"role": est_input.get("role"), "content": est_input.get("content")})
                                else:
                                    try:
                                        s = json.dumps(est_input) if not isinstance(est_input, str) else est_input
                                    except Exception:
                                        s = str(est_input)
                                    estimation_messages.append({"role": "assistant", "content": s})
                            else:
                                # Single string or other single item
                                estimation_messages.append({"role": "assistant", "content": str(est_input)})
                            try:
                                estimated_tokens = estimate_response_tokens(estimation_messages)
                                logger.debug(f"Estimated tokens for summarization payload before sending: {estimated_tokens}")
                            except Exception:
                                logger.debug("Failed to estimate tokens for summarization payload before sending")
                        except Exception:
                            logger.exception("Failed building estimation messages for summarization payload")

                        # H3: Preflight rate-limit gate for summarization follow-up.
                        # Previously this call only recorded tokens post-hoc,
                        # allowing the summarization burst to bypass the
                        # configured TPM cap.
                        summary_preflight_ok = True
                        try:
                            if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
                                try:
                                    summary_preflight_tokens = int(estimated_tokens) if estimated_tokens is not None else 0
                                except Exception:
                                    summary_preflight_tokens = 0
                                if summary_preflight_tokens <= 0:
                                    try:
                                        summary_input = summary_params.get(REQUEST_PARAM_INPUT)
                                        if isinstance(summary_input, list):
                                            summary_preflight_tokens = count_message_tokens(summary_input)
                                        elif summary_input is not None:
                                            summary_preflight_tokens = count_message_tokens(
                                                [{"role": "user", "content": str(summary_input)}]
                                            )
                                    except Exception:
                                        logger.exception(
                                            "Failed to estimate summarization payload tokens for rate-limit preflight; using 0"
                                        )
                                        summary_preflight_tokens = 0
                                wait_result = rate_limiter.RATE_LIMITER.wait_if_needed(summary_preflight_tokens)
                                if wait_result is None:
                                    logger.warning(
                                        "Skipping summarization follow-up: estimated tokens (%s) exceed rate-limiter safety threshold",
                                        summary_preflight_tokens,
                                    )
                                    summary_preflight_ok = False
                        except Exception:
                            logger.exception(
                                "Rate-limit preflight check failed for summarization follow-up; proceeding without gating"
                            )

                        if not summary_preflight_ok:
                            summary_response = None
                        else:
                            # Summarization call with cancellable helper and label
                            summary_response = _cancellable_responses_create(client.responses.create, summary_params, progress_label="Summarizing ")

                        logger.debug("Received summarization follow-up response from OpenAI Responses API")

                        # Persist summary response id
                        try:
                            summary_id = getattr(summary_response, ID_KEY, None)
                            if summary_id:
                                setattr(config, "RESPONSE_ID", summary_id)
                                logger.debug(
                                    f"Persisted summarization response id {summary_id} into config.RESPONSE_ID"
                                )
                        except Exception:
                            logger.debug("Failed to persist summarization response id to config, continuing")

                        # Extract token usage for summary response
                        summary_tokens = None
                        summary_used_estimate = False
                        try:
                            usage = getattr(summary_response, "usage", None)
                            if usage is None:
                                summary_tokens = None
                                summary_used_estimate = True
                            else:
                                if isinstance(usage, dict):
                                    summary_tokens = (
                                        usage.get(USAGE_KEYS[0])
                                        or usage.get(USAGE_KEYS[1])
                                        or usage.get(USAGE_KEYS[2])
                                    )
                                else:
                                    summary_tokens = (
                                        getattr(usage, USAGE_KEYS[0], None)
                                        or getattr(usage, USAGE_KEYS[1], None)
                                        or getattr(usage, USAGE_KEYS[2], None)
                                    )
                                if summary_tokens is None:
                                    summary_used_estimate = True
                                else:
                                    summary_used_estimate = False
                        except Exception:
                            summary_tokens = None
                            summary_used_estimate = True

                        if summary_tokens is None:
                            summary_tokens = 0

                        # Update token usage and rate limiter for summary
                        try:
                            update_token_usage(
                                summary_tokens,
                                used_estimate=summary_used_estimate,
                                response=summary_response,
                                model=summary_resolved_model,
                            )
                            logger.debug(
                                f"Updated token usage with {summary_tokens} tokens from summarization OpenAI response"
                            )
                        except Exception:
                            logger.exception(
                                "Failed to update token usage after summarization OpenAI response"
                            )

                        try:
                            if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
                                rate_limiter.RATE_LIMITER.add_request(summary_tokens)
                                logger.debug(
                                    f"Added summarization request of {summary_tokens} tokens to rate limiter"
                                )
                        except Exception:
                            logger.exception(
                                "Failed to add summarization request to rate limiter after OpenAI response"
                            )

                        # Safely add summary_tokens to actual_tokens so total token accounting includes the summary follow-up
                        try:
                            if actual_tokens is None:
                                actual_tokens = 0
                            try:
                                # Attempt numeric addition; coerce to int if possible
                                if isinstance(summary_tokens, (int, float)):
                                    actual_tokens += int(summary_tokens)
                                    logger.debug(
                                        f"Added {summary_tokens} summary tokens to actual_tokens, new total: {actual_tokens}"
                                    )
                                else:
                                    # Try to coerce strings that represent integers
                                    if isinstance(summary_tokens, str) and summary_tokens.isdigit():
                                        actual_tokens += int(summary_tokens)
                                        logger.debug(
                                            f"Coerced and added summary tokens '{summary_tokens}' to actual_tokens, new total: {actual_tokens}"
                                        )
                                    else:
                                        logger.debug(
                                            f"Summary tokens value not numeric, skipping addition to actual_tokens: {summary_tokens}"
                                        )
                            except Exception:
                                logger.exception("Failed while attempting to coerce and add summary_tokens to actual_tokens")
                        except Exception:
                            logger.exception("Failed to add summary_tokens to actual_tokens")

                        # Replace last_response with the summary response so normalization returns the summary
                        last_response = summary_response
                    except Exception:
                        logger.exception("Failed to send or process summarization follow-up; proceeding without summary")
        except Exception:
            # Any unexpected error in summarization handling should not prevent normal flow
            logger.exception("Unexpected error while attempting summarization follow-up")

        # After loop finishes, normalize the last_response into wrapper as before
        output_text = ""
        try:
            # Prefer output_text if present
            if hasattr(last_response, OUTPUT_TEXT_ATTR) and getattr(last_response, OUTPUT_TEXT_ATTR):
                output_text = getattr(last_response, OUTPUT_TEXT_ATTR)
            else:
                # Attempt to extract from response.output which may be a list of items
                output = getattr(last_response, OUTPUT_KEY, None)
                if output is None:
                    # Some SDKs might store textual output under 'choices' or other shapes
                    # Try to read last_response.get('output') if possible
                    try:
                        output = last_response.get(OUTPUT_KEY)  # type: ignore
                    except Exception:
                        output = None
                if isinstance(output, str):
                    output_text = output
                elif isinstance(output, list):
                    parts = []
                    for item in output:
                        if item is None:
                            continue
                        if isinstance(item, str):
                            parts.append(item)
                        elif isinstance(item, dict):
                            # common key names: 'content', 'text', 'message'
                            if CONTENT_KEY in item:
                                content = item[CONTENT_KEY]
                                if isinstance(content, list):
                                    # list of dicts or strings
                                    for sub in content:
                                        if isinstance(sub, str):
                                            parts.append(sub)
                                        elif isinstance(sub, dict):
                                            # nested content may have 'text' or 'content'
                                            parts.append(sub.get(TEXT_KEY) or sub.get(CONTENT_KEY) or "")
                                elif isinstance(content, str):
                                    parts.append(content)
                            elif TEXT_KEY in item:
                                parts.append(item.get(TEXT_KEY) or "")
                            elif MESSAGE_KEY in item and isinstance(item.get(MESSAGE_KEY), dict):
                                msg = item.get(MESSAGE_KEY)
                                # message may contain 'content' as string or list
                                if isinstance(msg.get(CONTENT_KEY), str):
                                    parts.append(msg.get(CONTENT_KEY))
                                elif isinstance(msg.get(CONTENT_KEY), list):
                                    for sub in msg.get(CONTENT_KEY):
                                        if isinstance(sub, str):
                                            parts.append(sub)
                                        elif isinstance(sub, dict):
                                            parts.append(sub.get(TEXT_KEY) or sub.get(CONTENT_KEY) or "")
                        else:
                            # Fallback string conversion
                            try:
                                parts.append(str(item))
                            except Exception:
                                pass
                    output_text = "".join(parts)
                elif isinstance(output, dict):
                    # Try common keys
                    if CONTENT_KEY in output:
                        c = output[CONTENT_KEY]
                        if isinstance(c, str):
                            output_text = c
                        elif isinstance(c, list):
                            output_text = "".join(
                                x if isinstance(x, str) else x.get(TEXT_KEY, "") for x in c
                            )
                    else:
                        # Try converting to string representation
                        try:
                            output_text = str(output)
                        except Exception:
                            output_text = ""
                else:
                    output_text = ""
        except Exception:
            output_text = ""

        # Build normalized wrapper expected by the rest of the system using last_response
        wrapper = {
            ID_KEY: getattr(last_response, ID_KEY, None),
            CHOICES_KEY: [{MESSAGE_KEY: {CONTENT_KEY: output_text}}],
            "usage": {USAGE_KEYS[0]: actual_tokens},
        }

        logger.debug("Normalized OpenAI response into internal wrapper format")
        return wrapper

    except Exception as e:
        if getattr(e, "code", None) == "context_length_exceeded":
            _log_context_length_exceeded(e, params)
        logger.error(f"Responses API call failed: {e}", exc_info=True)
        raise

def response_completion(user_input, tool_descriptions, gemini_tool_descriptions, log_prefix="", error_message="Error during responses API completion"):
    """Main entry point for responses API completion.

    This function handles the complete flow for responses API:
    1. Validates configuration
    2. Prepares messages
    3. Estimates tokens
    4. Validates messages
    5. Calls responses API (cancellable via Ctrl-C)
    6. Processes response
    7. Updates token usage

    Ctrl-C will cancel an in-flight API wait and return (None, "Cancelled by user").

    Args:
        user_input (str): The user's input/query
        tool_descriptions (list): Tool specifications for the current model
        gemini_tool_descriptions (list): Alternative tool specifications (for Gemini models)
        log_prefix (str): Prefix for log messages
        error_message (str): Default error message

    Returns:
        tuple: (response, error_message) where response is None on error or cancellation
    """
    try:
        logger.debug(f"{log_prefix} Starting responses API completion")

        # Validate configuration
        validate_responses_config()

        # Prepare messages for responses API
        messages = prepare_response_messages(user_input)

        # Estimate token count
        estimated_tokens = estimate_response_tokens(messages)

        # Compute estimated request including reasoning completion budget if applicable
        reasoning_allowance = (getattr(config, "REASONING_MAX_COMPLETION_TOKENS", 0) if is_reasoning_model(getattr(config, "MODEL", None), getattr(config, "REASONING_MODEL_PREFIX", None)) else 0)
        estimated_request = estimated_tokens + (reasoning_allowance or 0)

        # Validate message order
        try:
            validate_tool_message_order(messages)
        except ValueError as ve:
            logger.error(f"Message validation failed for responses API: {ve}")
            return None, str(ve)

        # Input window gating for responses API
        input_window_limit = _resolve_model_input_window()
        if input_window_limit is None:
            logger.debug("Input size gating is disabled: no valid MODEL_INPUT_WINDOW or MODEL_CONTEXT_WINDOW configured (responses API)")
        else:
            effective_input_window_limit = int(
                input_window_limit * _get_followup_base_safety_ratio()
            )
            if estimated_tokens > effective_input_window_limit:
                error_msg = (
                    f"Input too large: {estimated_tokens} tokens vs effective input window "
                    f"{effective_input_window_limit} (safety-margined from {input_window_limit}). "
                    f"Cannot send request to responses API. Please reduce your input or send a smaller request."
                )
                logger.error(error_msg)
                return None, error_msg

        # Apply rate limiting if configured
        if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
            wait_result = rate_limiter.RATE_LIMITER.wait_if_needed(estimated_request)
            if wait_result is None:
                error_msg = (
                    f"Rate limit safety threshold exceeded: {estimated_request} tokens. "
                    f"Model TPM limit {config.MODEL_MAX_TPM}. Reduce your input or wait before retrying."
                )
                logger.error(error_msg)
                return None, error_msg

        # M-rl2: per-request UUID shared between the cancellation and the
        # success-path accounting. If both fire (cancel records the estimate,
        # then the eventual provider response is processed and records the
        # actual count), add_request replaces the entry in place instead of
        # double-counting.
        request_id = uuid.uuid4().hex

        # Call responses API
        try:
            api_response = call_responses_api(messages, tool_descriptions, gemini_tool_descriptions, request_id=request_id)
        except KeyboardInterrupt:
            logger.info("Responses API call cancelled by user via Ctrl-C")
            # Conservative token accounting on cancellation
            try:
                update_token_usage(estimated_request, used_estimate=True)
                logger.debug(f"Conservatively updated token usage with {estimated_request} tokens on cancellation")
            except Exception:
                logger.exception("Failed to conservatively update token usage on cancellation")
            try:
                if hasattr(config, "RATE_LIMITER") and rate_limiter.RATE_LIMITER:
                    rate_limiter.RATE_LIMITER.add_request(estimated_request, request_id=request_id)
                    logger.debug(f"Conservatively added cancellation request of {estimated_request} tokens to rate limiter (request_id={request_id})")
            except Exception:
                logger.exception("Failed to conservatively add cancellation request to rate limiter")
            return None, "Cancelled by user"

        # Convert response format
        response = convert_response_format(api_response)

        logger.debug(f"{log_prefix} Successfully completed responses API request")
        return response, None

    except Exception as e:
        return handle_response_errors(e, user_input)


def get_response_initial_completion(user_input, tool_descriptions, gemini_tool_descriptions):
    """Get initial response from responses API for the query.

    Args:
        user_input (str): The user's input/query
        tool_descriptions (list): Tool specifications for the current model
        gemini_tool_descriptions (list): Alternative tool specifications (for Gemini models)

    Returns:
        tuple: (response, error_message) where response is None on error
    """
    logger.debug("Getting initial responses API response...")
    return response_completion(
        user_input,
        tool_descriptions,
        gemini_tool_descriptions,
        log_prefix="Initial responses API request:",
        error_message="I apologize, but I encountered an error processing your request via responses API. Please try again",
    )
