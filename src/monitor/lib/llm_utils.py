"""Utility helpers for LLM processing moved out of core/llm.py for reuse and clarity.

This module contains lightweight helpers and adapters that the core llm orchestration
imports. It intentionally mirrors the behavior in src/monitor/core/llm.py at the time
of extraction; any future refactorings should update both caller sites as needed.
"""

import logging
import re
from importlib import import_module
from typing import Any, Dict, List, Optional, Tuple, Union, cast

import litellm

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpcore
    import httpx
    import ollama
    from monitor.lib import rate_limiter
else:
    httpcore = import_module("httpcore")
    httpx = import_module("httpx")
    try:
        from monitor.lib import rate_limiter
    except Exception:
        rate_limiter = None
    try:
        import ollama
    except Exception:
        ollama = None

from monitor import config
from monitor.lib.llm_model_utils import (
    DEFAULT_TOOL_TYPE,
    DESCRIPTION_KEY,
    NAME_KEY,
    OPENAI_PREFIX,
    PARAMETERS_PROPERTIES_KEY,
    PARAMETERS_REQUIRED_KEY,
    PARAMETERS_TYPE_OBJECT,
    TYPE_KEY,
    get_model_head,
    get_model_tail,
    effective_turn_effort,
    is_reasoning_model,
    normalize_tool_descriptors,
    resolve_turn_model,
    strip_openai_prefix,
)
from monitor.lib.llm_output_utils import (
    build_function_call_output_item,
    build_summarization_followup_params,
    serialize_tool_output,
)
from monitor.lib.llamacpp_adapter import adapt_llamacpp_chat_response
from monitor.lib.ollama_adapter import adapt_ollama_chat_response
from monitor.lib.llm_usage_utils import (
    compute_token_delta,
    safe_extract_total_tokens,
    truncate_to_token_limit,
)


def append_to_history_with_count(*args, **kwargs):
    """Proxy history append calls through a lazy import.

    Args:
        *args: Positional arguments forwarded to
            ``monitor.lib.history.append_to_history_with_count``.
        **kwargs: Keyword arguments forwarded to
            ``monitor.lib.history.append_to_history_with_count``.

    Returns:
        The proxied append result.
    """
    from monitor.lib.history import append_to_history_with_count as history_append

    return history_append(*args, **kwargs)
from monitor.lib.message_utils import normalize_message, sanitize_messages
from monitor.lib.text_to_speech import TextToSpeech
from monitor.lib.tool_loading import function_descriptions
from monitor.lib.tool_profiles import advertised_tool_descriptors_for_current_turn

logger = logging.getLogger(__name__)

TTS = TextToSpeech()



class AttrDict(dict):
    """
    Dictionary subclass whose entries can be accessed by attributes (as well as normally).
    Useful for converting dict-style API responses to attribute-accessible objects.
    """
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        for key, value in self.items():
            setattr(self, key, self._wrap(value))

    def __setitem__(self, key, value):
        super(AttrDict, self).__setitem__(key, value)
        setattr(self, key, self._wrap(value))

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def _wrap(self, value):
        if isinstance(value, dict):
            return AttrDict(value)
        elif isinstance(value, list):
            return [self._wrap(item) for item in value]
        return value


def dict_to_attr(obj):
    if isinstance(obj, dict):
        return AttrDict({k: dict_to_attr(v) for k, v in obj.items()})
    elif isinstance(obj, list):
        return [dict_to_attr(v) for v in obj]
    else:
        return obj


def validate_tool_message_order(messages):
    """
    Validate that 'tool' role messages immediately follow an assistant message with matching tool_calls.
    Maintains a set of pending tool_call ids from the most recent assistant tool_calls.
    Clears the pending set after the first non-tool message following the assistant/tool_calls sequence.
    Raises ValueError if any 'tool' message violates the order or has unknown tool_call_id.
    Also validates that assistant messages with tool_calls contain a non-empty list and that each tool_call has an id.
    """
    pending = {}
    in_tool_phase = False
    for idx, msg in enumerate(messages):
        role = msg.get("role")
        if role == "assistant":
            tool_calls = msg.get("tool_calls", None)
            if tool_calls is not None:
                if not isinstance(tool_calls, list):
                    raise ValueError(f"Invalid assistant message at index {idx}: tool_calls must be a list when present.")
                if len(tool_calls) == 0:
                    raise ValueError(f"Invalid assistant message at index {idx}: tool_calls must not be an empty list.")
                for tc in tool_calls:
                    tc_id = None
                    if isinstance(tc, dict):
                        tc_id = tc.get("id")
                    else:
                        tc_id = getattr(tc, "id", None)
                    if not tc_id:
                        raise ValueError(f"Invalid assistant tool_call at index {idx}: missing id.")
            tool_calls = tool_calls or []
            pending = {tc.get("id"): True for tc in tool_calls if isinstance(tc, dict) and tc.get("id")}
            # If tool_calls are objects, include their ids as well
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    tc_id_obj = getattr(tc, "id", None)
                    if tc_id_obj:
                        pending[tc_id_obj] = True
            in_tool_phase = len(pending) > 0
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id")
            if not in_tool_phase or not pending or tool_call_id not in pending:
                raise ValueError(
                    f"Invalid tool message at index {idx}: unexpected tool_call_id '{tool_call_id}'. "
                    "Tool messages must immediately follow an assistant message with matching tool_calls."
                )
            pending.pop(tool_call_id, None)
        else:
            if in_tool_phase:
                pending = {}
                in_tool_phase = False




def _extract_assistant_text(message):
    """Extract assistant text from provider-specific message shapes.

    Args:
        message: A provider response message object or dict.

    Returns:
        A best-effort assistant text string.
    """
    if isinstance(message, dict):
        content = message.get("content")
        text = message.get("text")
    else:
        content = getattr(message, "content", None)
        text = getattr(message, "text", None)

    if isinstance(content, str) and content:
        return content
    if isinstance(text, str) and text:
        return text
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item.get("text", ""))
                elif isinstance(item.get("content"), str):
                    parts.append(item.get("content", ""))
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)
def determine_response_type(response_message):
    """Determine the type of response and how to handle it"""
    logger.debug("Determining response type...")

    if hasattr(response_message, 'tool_calls') and response_message.tool_calls and len(response_message.tool_calls) > 0:
        return "tool_call"
    elif hasattr(response_message, 'function_call') and response_message.function_call:
        return "function_call"
    else:
        return "direct"


def process_direct_response(response_message):
    """Process a direct (non-function-call) response from LLM"""
    from monitor.lib.token_management import count_message_tokens, update_token_usage

    logger.info("Processing direct LLM response; response_message_type=%s", type(response_message).__name__)
    assistant_message = normalize_message(response_message)
    assistant_content = assistant_message.get("content", "")
    extracted_content = _extract_assistant_text(response_message)
    if isinstance(extracted_content, str) and extracted_content and assistant_content != extracted_content:
        logger.info("Direct response extractor found alternate assistant text shape")
        assistant_content = extracted_content
    if isinstance(assistant_content, list):
        logger.info("Direct response content arrived as list; normalizing to text")
        assistant_content = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in assistant_content
        )
    elif assistant_content is None:
        logger.info("Direct response content is None; normalizing to empty string")
        assistant_content = ""
    logger.info(
        "Direct response normalized; assistant_message_keys=%s content_type=%s content_length=%s",
        sorted(list(assistant_message.keys())) if isinstance(assistant_message, dict) else type(assistant_message).__name__,
        type(assistant_content).__name__,
        len(assistant_content) if isinstance(assistant_content, str) else -1,
    )

    # Log and update conversation history
    if (config.CONVERSATION_LOG_FILE and not config.CONVERSATION_LOG_FILE.closed):
        try:
            config.CONVERSATION_LOG_FILE.write(f"AI: {assistant_content}\n")
        except Exception:
            logger.exception("Failed writing to conversation log file.")
    append_to_history_with_count(
        assistant_message,
        config.CONVERSATION_HISTORY,
        count_message_tokens,
        update_token_usage
    )

    if getattr(config, "LAST_INPUT_WAS_VOICE", False):
        try:
            TTS.speak(assistant_content)
        except Exception:
            logger.exception("TTS speak failed")
        config.LAST_INPUT_WAS_VOICE = False

    return assistant_content


def extract_tool_calls(response):
    """Extract and validate tool calls from LLM response"""
    from monitor.lib.token_management import count_message_tokens, update_token_usage
    
    # Defensive check for choices
    if not getattr(response, "choices", None) or len(response.choices) == 0:
        raise ValueError("Malformed response: missing choices for tool extraction")

    msg = response.choices[0].message
    logger.info(
        "Extracting tool calls; response_type=%s message_type=%s finish_reason=%s",
        type(response).__name__,
        type(msg).__name__,
        getattr(response.choices[0], "finish_reason", None),
    )
    tool_calls = getattr(msg, "tool_calls", None) or []
    try:
        ids_presence = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                ids_presence.append(bool(tc.get("id")))
            else:
                ids_presence.append(bool(getattr(tc, "id", None)))
        logger.debug(f"Tool calls count: {len(tool_calls)}; all_have_ids={all(ids_presence)}")
    except Exception as e:
        logger.error(f"Unable to evaluate tool_call id presence: {e}")
    normalized_msg = normalize_message(msg)
    # Ensure we have a mutable dict to work with
    if not isinstance(normalized_msg, dict):
        try:
            if hasattr(normalized_msg, "to_dict"):
                normalized_msg = normalized_msg.to_dict()
            elif hasattr(normalized_msg, "__dict__"):
                normalized_msg = {k: v for k, v in normalized_msg.__dict__.items() if not k.startswith("_")}
            else:
                normalized_msg = dict(normalized_msg)
        except Exception:
            normalized_msg = {"role": getattr(msg, "role", "assistant"), "content": getattr(msg, "content", None)}
    # Rebuild tool_calls into list of dicts when present and non-empty; otherwise remove key
    rebuilt_tool_calls = []
    if isinstance(tool_calls, list) and len(tool_calls) > 0:
        for tc in tool_calls:
            if isinstance(tc, dict):
                rebuilt_tool_calls.append(tc)
            else:
                try:
                    if hasattr(tc, "to_dict"):
                        rebuilt_tool_calls.append(tc.to_dict())
                    elif hasattr(tc, "__dict__"):
                        rebuilt_tool_calls.append({k: v for k, v in tc.__dict__.items() if not k.startswith("_")})
                    else:
                        rebuilt_tool_calls.append({"id": getattr(tc, "id", None)})
                except Exception:
                    rebuilt_tool_calls.append({"id": getattr(tc, "id", None)})
        normalized_msg["tool_calls"] = rebuilt_tool_calls
    else:
        if "tool_calls" in normalized_msg:
            try:
                del normalized_msg["tool_calls"]
            except Exception:
                normalized_msg["tool_calls"] = []
                try:
                    del normalized_msg["tool_calls"]
                except Exception:
                    pass
    # Sanitize and append the single message
    try:
        sanitized_list = sanitize_messages([normalized_msg])
    except Exception as e:
        logger.error(f"sanitize_messages failed in extract_tool_calls: {e}")
        sanitized_list = [normalized_msg]
    sanitized_msg = sanitized_list[0] if isinstance(sanitized_list, list) and sanitized_list else normalized_msg
    append_to_history_with_count(
        sanitized_msg,
        config.CONVERSATION_HISTORY,
        count_message_tokens,
        update_token_usage
    )
    # Return the sanitized message's tool_calls as a list of dicts, default empty
    return sanitized_msg.get("tool_calls", []) if isinstance(sanitized_msg, dict) else []


def process_response_by_finish_reason(response):
    """Process the LLM response and determine next action"""
    choices = getattr(response, "choices", None)
    if choices is None or len(choices) == 0:
        raise ValueError("Malformed response: missing choices when processing finish reason")

    finish_reason = (choices[0].finish_reason or '').lower()

    # openai uses 'refusal'
    # grok uses 'content_filter'
    # gemini uses 'safety'
    if finish_reason == "refusal" or finish_reason == "content_filter" or finish_reason == "safety":
        logger.error("The request was refused due to policy violations.")
        # Remove the last turn (user input and any assistant response) from conversation history
        if len(config.CONVERSATION_HISTORY) >= 1:
            # Remove the last user message that caused the refusal
            last_message = config.CONVERSATION_HISTORY[-1]
            if last_message.get('role') == 'user':
                config.CONVERSATION_HISTORY.pop()
                # Pop the matching per-turn cost bucket in lockstep. That
                # bucket was opened when the user message landed in history
                # (see append_to_history_with_count). With no LLM cost
                # recorded for a refused call, leaving it would surface as
                # a phantom $0.00 last-turn entry in the U: indicator that
                # never goes away.
                try:
                    turn_costs = getattr(config, "TURN_COSTS_USD", None)
                    if isinstance(turn_costs, list) and turn_costs:
                        turn_costs.pop()
                        config.TURN_COSTS_USD = turn_costs
                except Exception:
                    logger.debug(
                        "Failed to pop TURN_COSTS_USD bucket on refusal", exc_info=True
                    )
                try:
                    round_trips = getattr(config, "TURN_ROUND_TRIPS", None)
                    if isinstance(round_trips, list) and round_trips:
                        round_trips.pop()
                        config.TURN_ROUND_TRIPS = round_trips
                except Exception:
                    logger.debug(
                        "Failed to pop TURN_ROUND_TRIPS bucket on refusal", exc_info=True
                    )
                logger.debug("Removed user message that caused refusal from conversation history")

            # If there's an assistant message that was also added, remove it too
            if len(config.CONVERSATION_HISTORY) >= 1:
                second_last_message = config.CONVERSATION_HISTORY[-1]
                if second_last_message.get('role') == 'assistant':
                    config.CONVERSATION_HISTORY.pop()
                    logger.debug("Removed assistant message from conversation history due to refusal")

        return "Request was refused."

    # openai uses length
    # gemini uses max_tokens
    if finish_reason == "length" or finish_reason == "max_tokens":
        logger.error("The conversation was too long for the context window.")
        return "Length too long."

    if finish_reason == "tool_calls":
        return None  # Indicate need for another tool call

    if finish_reason == "stop":
        assistant_message = choices[0].message
        assistant_content = _extract_assistant_text(assistant_message)
        logger.info(
            "Stop finish_reason received; assistant_message_type=%s content_type=%s content_preview=%r",
            type(assistant_message).__name__,
            type(assistant_content).__name__,
            assistant_content[:120] if isinstance(assistant_content, str) else assistant_content,
        )
        if isinstance(assistant_content, list):
            logger.info("Stop response content arrived as list; joining text blocks")
            assistant_content = "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in assistant_content
            )
        if (config.CONVERSATION_LOG_FILE and not config.CONVERSATION_LOG_FILE.closed):
            try:
                config.CONVERSATION_LOG_FILE.write(f"AI: {assistant_content}\n")
            except Exception:
                logger.exception("Failed writing assistant content to conversation log file")

        # _extract_assistant_text normalizes a None content to "" (empty string),
        # so check for falsy content (None, "", {}) — not just None/{} — otherwise
        # an empty assistant response returns "" to the user instead of the
        # intended acknowledgement.
        if not assistant_content or assistant_content == {}:
            logger.info("Stop response content was empty; returning default acknowledgement")
            return "Ok."
        return assistant_content

    if config.MODEL and isinstance(config.MODEL, str) and "xai/grok" in config.MODEL and finish_reason == "":
        return None  # Indicate need for another tool call

    logger.error(f"Unexpected finish_reason: {finish_reason} - {choices[0]}")
    return f"Unexpected finish reason: {finish_reason}"



def _call_native_ollama_completion(
    messages: list,
    model: str,
    tools: list[dict[str, Any]] | None = None,
):
    """Call Ollama directly with the native Python client.

    Args:
        messages: Chat messages in Ollama-compatible format.
        model: The Ollama model tail (e.g. ``ornith:9b``).
        tools: Optional tool schemas to send with the Ollama request.

    Returns:
        The native Ollama response object.
    """
    native_ollama = cast(Any, ollama)
    if native_ollama is None:
        raise RuntimeError("ollama Python package is not available")
    base_url = getattr(config, "OLLAMA_BASE_URL", None)
    options = {}
    ollama_temperature = getattr(config, "OLLAMA_TEMPERATURE", None)
    if isinstance(ollama_temperature, (int, float)):
        options["temperature"] = float(ollama_temperature)
    ollama_top_p = getattr(config, "OLLAMA_TOP_P", None)
    if isinstance(ollama_top_p, (int, float)):
        options["top_p"] = float(ollama_top_p)
    ollama_top_k = getattr(config, "OLLAMA_TOP_K", None)
    if isinstance(ollama_top_k, int):
        options["top_k"] = ollama_top_k
    ollama_context_window = getattr(config, "OLLAMA_MODEL_CONTEXT_WINDOW", None)
    if isinstance(ollama_context_window, int):
        options["num_ctx"] = ollama_context_window
    ollama_output_window = getattr(config, "OLLAMA_MODEL_OUTPUT_WINDOW", None)
    if isinstance(ollama_output_window, int):
        options["num_predict"] = ollama_output_window
    logger.info(
        "Dispatching native Ollama call with model=%s base_url=%s options=%s message_count=%s tool_count=%s",
        model,
        base_url,
        options,
        len(messages) if isinstance(messages, list) else -1,
        len(tools) if isinstance(tools, list) else 0,
    )
    if isinstance(base_url, str) and base_url.strip():
        client = native_ollama.Client(host=base_url.strip())
    else:
        client = native_ollama.Client()
    request_payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "options": options or None,
        "host": base_url,
    }
    if tools is not None:
        request_payload["tools"] = tools
    logger.info("Ollama native request payload: %r", request_payload)
    response = client.chat(
        model=model,
        messages=messages,
        tools=tools,
        options=options or None,
    )
    return adapt_ollama_chat_response(response)


def _call_native_llamacpp_completion(
    messages: list,
    model: str,
    tools: list[dict[str, Any]] | None = None,
    max_completion_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
):
    """Call a llama.cpp chat-completions server directly.

    Args:
        messages: Chat messages in OpenAI-compatible format.
        model: The llama.cpp model tail to send in the request.
        tools: Optional tool schemas to send with the request.
        max_completion_tokens: Optional output-token cap for compatible servers.
        temperature: Optional sampling temperature override.
        top_p: Optional nucleus sampling override.
        top_k: Optional top-k sampling override.

    Returns:
        The normalized llama.cpp response object.
    """
    base_url = getattr(config, "LLAMACPP_BASE_URL", None) or "http://localhost:8080/v1"
    if not isinstance(base_url, str) or not base_url.strip():
        raise RuntimeError("LLAMACPP_BASE_URL must be a non-empty string")
    base_url = base_url.strip().rstrip("/")
    endpoint_url = f"{base_url}/chat/completions"

    request_payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if isinstance(tools, list):
        request_payload["tools"] = tools

    effective_temperature = temperature
    if effective_temperature is None:
        config_temperature = getattr(config, "LLAMACPP_TEMPERATURE", None)
        if isinstance(config_temperature, (int, float)):
            effective_temperature = float(config_temperature)
    if isinstance(effective_temperature, (int, float)):
        request_payload["temperature"] = float(effective_temperature)

    effective_top_p = top_p
    if effective_top_p is None:
        config_top_p = getattr(config, "LLAMACPP_TOP_P", None)
        if isinstance(config_top_p, (int, float)):
            effective_top_p = float(config_top_p)
    if isinstance(effective_top_p, (int, float)):
        request_payload["top_p"] = float(effective_top_p)

    effective_top_k = top_k
    if effective_top_k is None:
        config_top_k = getattr(config, "LLAMACPP_TOP_K", None)
        if isinstance(config_top_k, int):
            effective_top_k = config_top_k
    if isinstance(effective_top_k, int):
        request_payload["top_k"] = effective_top_k

    if isinstance(max_completion_tokens, int) and max_completion_tokens > 0:
        request_payload["max_tokens"] = max_completion_tokens

    logger.info(
        "Dispatching native llama.cpp call with model=%s endpoint=%s message_count=%s tool_count=%s",
        model,
        endpoint_url,
        len(messages) if isinstance(messages, list) else -1,
        len(tools) if isinstance(tools, list) else 0,
    )

    headers = {"Content-Type": "application/json"}
    api_key = getattr(config, "LLAMACPP_API_KEY", None)
    if isinstance(api_key, str) and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    response = httpx.post(
        endpoint_url,
        json=request_payload,
        headers=headers,
        timeout=300.0,
    )
    response.raise_for_status()
    return adapt_llamacpp_chat_response(response.json())

def _apply_provider_request_normalization(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize provider-specific request kwargs before dispatch.

    Args:
        kwargs: The completion kwargs built for LiteLLM.

    Returns:
        The normalized kwargs dictionary.
    """
    model_name = kwargs.get("model")
    if isinstance(model_name, str) and model_name.lower().startswith("ollama/"):
        base_url = getattr(config, "OLLAMA_BASE_URL", None)
        if isinstance(base_url, str) and base_url.strip():
            kwargs["api_base"] = base_url.strip()
        ollama_temperature = getattr(config, "OLLAMA_TEMPERATURE", None)
        if isinstance(ollama_temperature, (int, float)):
            kwargs["temperature"] = float(ollama_temperature)
        ollama_top_p = getattr(config, "OLLAMA_TOP_P", None)
        if isinstance(ollama_top_p, (int, float)):
            kwargs["top_p"] = float(ollama_top_p)
        ollama_top_k = getattr(config, "OLLAMA_TOP_K", None)
        if isinstance(ollama_top_k, int):
            kwargs["top_k"] = ollama_top_k
        kwargs.pop("reasoning_effort", None)
    if isinstance(model_name, str) and model_name.lower().startswith("llamacpp/"):
        kwargs.pop("reasoning_effort", None)
        llamacpp_temperature = getattr(config, "LLAMACPP_TEMPERATURE", None)
        if isinstance(llamacpp_temperature, (int, float)):
            kwargs["temperature"] = float(llamacpp_temperature)
        llamacpp_top_p = getattr(config, "LLAMACPP_TOP_P", None)
        if isinstance(llamacpp_top_p, (int, float)):
            kwargs["top_p"] = float(llamacpp_top_p)
        llamacpp_top_k = getattr(config, "LLAMACPP_TOP_K", None)
        if isinstance(llamacpp_top_k, int):
            kwargs["top_k"] = llamacpp_top_k
    return kwargs


def log_helper_model_usage(feature: str, model: str | None) -> None:
    """Record helper-model usage in the session log and counters.

    Args:
        feature: Name of the helper feature invoking the model.
        model: Model name used for the helper request.

    Returns:
        None.
    """
    try:
        config.SESSION_SPEND_HELPER_CALLS = int(
            getattr(config, "SESSION_SPEND_HELPER_CALLS", 0) or 0
        ) + 1
    except Exception:
        logger.debug("[SPEND][HELPER] Failed to bump helper-call counter", exc_info=True)
    logger.info("[SPEND][HELPER] feature=%s model=%s", feature, model)


def call_litellm_completion(
    model: str,
    messages: list,
    tool_descriptions: List[Dict[str, Any]],
    gemini_tool_descriptions: List[Dict[str, Any]],
    reasoning_effort: Any = None,
    max_completion_tokens: Any = None,
    temperature: Any = None,
    top_p: Any = None,
    top_k: Any = None,
):
    """
    Wrapper that adds `reasoning_effort` and `max_completion_tokens` when the
    model name contains the configured reasoning model prefix.

    Args:
        model: The full model identifier, e.g., 'openai/o3-2025-04-16'
        messages: The list of chat messages for the request.

    Returns:
        The litellm completion response.
    """
    tools, _tool_choice = get_tools_for_model(
        tool_descriptions,
        gemini_tool_descriptions,
        model_name=model,
        normalize_tools=False,
    )
    kwargs = {
        "model": model,
        "messages": messages,
        "drop_params": True,
    }
    if tools is not None:
        kwargs["tools"] = tools
    if isinstance(reasoning_effort, str) and reasoning_effort.strip():
        kwargs["reasoning_effort"] = reasoning_effort.strip()
    if isinstance(max_completion_tokens, int) and max_completion_tokens > 0:
        kwargs["max_completion_tokens"] = max_completion_tokens
    if isinstance(temperature, (int, float)):
        kwargs["temperature"] = float(temperature)
    if isinstance(top_p, (int, float)):
        kwargs["top_p"] = float(top_p)
    if isinstance(top_k, int):
        kwargs["top_k"] = top_k

    prefix = getattr(config, "REASONING_MODEL_PREFIX", None)
    if isinstance(prefix, str):
        prefix = prefix.strip()
    is_reasoning = False
    if isinstance(prefix, str) and prefix:
        try:
            pattern = re.compile(re.escape(prefix), re.IGNORECASE)
            if pattern.search(model):
                is_reasoning = True
                # Per-turn override (set by the auto-bump heuristic in
                # prepare_query_context, or by tool-failure escalation in
                # tooling.py) wins over the configured default for the duration
                # of this user turn. The override is one-way (only ever bumps
                # up — to medium or, on tool failure, high), so reading it
                # unconditionally never causes a surprise downgrade.
                override = getattr(config, "CURRENT_TURN_REASONING_OVERRIDE", None)
                collation = bool(getattr(config, "CURRENT_TURN_IS_COLLATION", False))
                effective_effort = effective_turn_effort(
                    config.REASONING_EFFORT,
                    override,
                    collation_active=collation,
                    orchestrator_effort=getattr(config, "ORCHESTRATOR_REASONING_EFFORT", None),
                )
                effective_max = config.REASONING_MAX_COMPLETION_TOKENS
                # Single-turn, transient model swap (kwargs only, never set_model):
                #   - collation/synthesis turn -> ORCHESTRATOR_MODEL
                #   - else a reasoning override -> ADV_REASONING_MODEL
                # So the configured default model, gauges, and session state are
                # all untouched, and the orchestrator backs down to MODEL after.
                swapped = resolve_turn_model(
                    model,
                    getattr(config, "ADV_REASONING_MODEL", None),
                    bool(override),
                    prefix,
                    orchestrator_model=getattr(config, "ORCHESTRATOR_MODEL", None),
                    collation_active=collation,
                    steady_provider=(
                        "ollama"
                        if isinstance(model, str) and (model.lower().startswith("ollama/") or model.upper() == "OLLAMA")
                        else "llamacpp"
                        if isinstance(model, str) and model.lower().startswith("llamacpp/")
                        else None
                    ),
                )
                if swapped != model:
                    kwargs["model"] = swapped
                    swapped_tools, _swapped_tool_choice = get_tools_for_model(
                        tool_descriptions,
                        gemini_tool_descriptions,
                        model_name=swapped,
                        normalize_tools=False,
                    )
                    if swapped_tools is not None:
                        kwargs["tools"] = swapped_tools
                    else:
                        kwargs.pop("tools", None)
                    # The ADV output-window cap applies only on an ADV swap.
                    if swapped == getattr(config, "ADV_REASONING_MODEL", None):
                        adv_out = getattr(config, "ADV_REASONING_MODEL_OUTPUT_WINDOW", None)
                        if (
                            isinstance(adv_out, int)
                            and adv_out > 0
                            and isinstance(effective_max, int)
                            and effective_max > 0
                        ):
                            effective_max = min(effective_max, adv_out)
                kwargs.update(
                    reasoning_effort=effective_effort,
                    max_completion_tokens=effective_max,
                    temperature=1,
                )
        except re.error:
            pass

    # For non-reasoning calls, apply the general MAX_COMPLETION_TOKENS cap so
    # the provider truncates long completions instead of running to whatever
    # the model picks on its own. Reasoning models already set their own,
    # larger cap above — don't overwrite it. drop_params=True lets litellm
    # translate the param name per provider.
    if not is_reasoning:
        _cap = getattr(config, "MAX_COMPLETION_TOKENS", None)
        if isinstance(_cap, int) and _cap > 0:
            kwargs["max_completion_tokens"] = _cap

    kwargs = _apply_provider_request_normalization(kwargs)
    model_name = kwargs.get("model")
    if isinstance(model_name, str) and model_name.lower().startswith("ollama/"):
        native_model = getattr(
            config,
            "OLLAMA_MODEL",
            model_name.split("/", 1)[1] if "/" in model_name else model_name,
        )
        native_messages = kwargs.get("messages", [])
        if not isinstance(native_messages, list):
            native_messages = []
        native_tools = kwargs.get("tools")
        if not isinstance(native_tools, list):
            native_tools = None
        if not isinstance(native_model, str):
            native_model = str(native_model)
        return _call_native_ollama_completion(
            native_messages,
            native_model,
            tools=native_tools,
        )
    if isinstance(model_name, str) and model_name.lower().startswith("llamacpp/"):
        native_model = getattr(config, "LLAMACPP_MODEL", None)
        if not isinstance(native_model, str) or not native_model.strip():
            native_model = model_name.split("/", 1)[1] if "/" in model_name else model_name
        native_messages = kwargs.get("messages", [])
        if not isinstance(native_messages, list):
            native_messages = []
        native_tools = kwargs.get("tools")
        if not isinstance(native_tools, list):
            native_tools = None
        native_max_completion_tokens = kwargs.get("max_completion_tokens")
        if not isinstance(native_max_completion_tokens, int):
            native_max_completion_tokens = None
        native_temperature = kwargs.get("temperature")
        if not isinstance(native_temperature, (int, float)):
            native_temperature = None
        native_top_p = kwargs.get("top_p")
        if not isinstance(native_top_p, (int, float)):
            native_top_p = None
        native_top_k = kwargs.get("top_k")
        if not isinstance(native_top_k, int):
            native_top_k = None
        if not isinstance(native_model, str):
            native_model = str(native_model)
        return _call_native_llamacpp_completion(
            native_messages,
            native_model,
            tools=native_tools,
            max_completion_tokens=native_max_completion_tokens,
            temperature=float(native_temperature) if isinstance(native_temperature, (int, float)) else None,
            top_p=float(native_top_p) if isinstance(native_top_p, (int, float)) else None,
            top_k=native_top_k,
        )
    return _call_litellm_completion_with_guard(**kwargs)


def _call_litellm_completion_with_guard(**kwargs: Any):
    """Call LiteLLM only after rejecting Ollama provider requests.

    Args:
        **kwargs: Completion kwargs forwarded to LiteLLM.

    Returns:
        The LiteLLM completion response.

    Raises:
        RuntimeError: If an Ollama model is about to be routed through LiteLLM.
    """
    model_name = kwargs.get("model")
    if isinstance(model_name, str) and model_name.lower().startswith("ollama/"):
        import traceback

        stack_trace = "".join(traceback.format_stack())
        logger.critical(
            "Fatal: Ollama model sent to LiteLLM completion. model=%s\n%s",
            model_name,
            stack_trace,
        )
        raise RuntimeError(
            f"Fatal: LiteLLM completion invoked for Ollama model '{model_name}'."
        )

    return litellm.completion(**kwargs)


ROLE_KEY = "role"
SYSTEM_ROLE = "system"
CONTENT_KEY = "content"
USER_ROLE = "user"

def prepare_response_messages(user_input):
    """Prepare messages for responses API format.

    The responses API typically expects a simpler format focused on the current request
    rather than full conversation history.

    Args:
        user_input (str): The current user input/query

    Returns:
        list: Formatted messages for responses API
    """
    try:
        # For responses API, we focus on the current request
        # Add system message if preferences are configured
        messages = []

        from monitor.lib.preferences import PREFERENCE_PROMPT

        if PREFERENCE_PROMPT:
            messages.append({ROLE_KEY: SYSTEM_ROLE, CONTENT_KEY: PREFERENCE_PROMPT})

        # Add the user input
        messages.append({ROLE_KEY: USER_ROLE, CONTENT_KEY: user_input})

        # Sanitize messages before sending
        messages = sanitize_messages(messages)

        logger.debug(f"Prepared {len(messages)} messages for responses API")
        return messages

    except Exception as e:
        logger.error(f"Error preparing response messages: {e}", exc_info=True)
        raise

def estimate_response_tokens(messages):
    """Estimate token count for responses API messages."""
    from monitor.lib.token_management import count_message_tokens, update_token_usage

    try:
        estimated_tokens = 0
        for msg in messages:
            normalized_msg = normalize_message(msg)
            estimated_tokens += count_message_tokens(normalized_msg)

        logger.debug(f"Estimated {estimated_tokens} tokens for responses API")
        return estimated_tokens

    except Exception as e:
        logger.error(f"Error estimating response tokens: {e}", exc_info=True)
        return 0

def get_tools_for_model(tool_descriptions, gemini_tool_descriptions, model_name=None, *, normalize_tools=True):
    """Get appropriate tool definitions based on the model type.

    Returns:
        tuple: (tools, tool_choice) where tools is the tool definitions and
               tool_choice is the tool selection strategy
    """
    try:
        model_value = (
            model_name
            if isinstance(model_name, str) and model_name
            else (getattr(config, "MODEL", "") or "")
        )
        model_lower = model_value.lower()

        # Check if tools are disabled
        if getattr(config, "DISABLE_TOOLS", False):
            logger.debug("Tools disabled by configuration")
            return None, None

        # Determine which tools to use based on model
        if "gemini" in model_lower:
            tools = gemini_tool_descriptions
            logger.debug(
                f"Using Gemini tool descriptions ({len(tools) if tools else 0} tools)"
            )
        else:
            tools = function_descriptions(tool_descriptions, gemini_tool_descriptions, model_lower)
            logger.debug(
                f"Using function descriptions ({len(tools) if tools else 0} tools)"
            )

        if tools:
            try:
                tools = advertised_tool_descriptors_for_current_turn(tools)
            except Exception:
                logger.exception("Failed to filter tools for the current profile, proceeding with original tools")

        # Normalize tool descriptors to a consistent flat shape for downstream usage
        if tools and normalize_tools:
            try:
                tools = normalize_tool_descriptors(tools)
            except Exception:
                logger.exception("Failed to normalize tool descriptors, proceeding with original tools")

        # Set tool choice strategy
        tool_choice = "auto" if tools else None

        return tools, tool_choice

    except Exception as e:
        logger.error(f"Error getting tools for model: {e}", exc_info=True)
        return None, None

CHOICES_KEY = "choices"
MESSAGE_KEY = "message"

def convert_response_format(api_response):
    """Convert responses API response to expected format.

    Ensures the response format matches what the rest of the system expects.

    Args:
        api_response (dict): Raw or normalized API response

    Returns:
        AttrDict: Converted response with attribute access
    """
    try:
        # Convert to attribute-accessible format
        response = dict_to_attr(api_response)

        # Validate expected response structure
        if not hasattr(response, CHOICES_KEY) or not response.choices:
            raise ValueError("Invalid response format: missing choices")

        if len(response.choices) == 0:
            raise ValueError("Invalid response format: empty choices")

        first_choice = response.choices[0]
        if not hasattr(first_choice, MESSAGE_KEY):
            raise ValueError("Invalid response format: missing message in choice")

        logger.debug("Successfully converted response format")
        return response

    except Exception as e:
        logger.error(f"Error converting response format: {e}", exc_info=True)
        raise

MAX_ERROR_INPUT_SNIPPET = 100

def handle_response_errors(error, user_input=None):
    """Handle responses API specific errors with appropriate logging.

    Args:
        error (Exception): The error that occurred
        user_input (str, optional): The original user input for context

    Returns:
        tuple: (None, error_message) following llm.py error format
    """
    # Detect network/connectivity-related errors and handle them specially.
    network_error_classes = []
    if httpcore is not None:
        try:
            network_error_classes.append(httpcore.ConnectError)
        except Exception:
            # If httpcore doesn't expose ConnectError as expected, ignore.
            pass
    if httpx is not None:
        try:
            network_error_classes.append(httpx.ConnectError)
        except Exception:
            # If httpx doesn't expose ConnectError as expected, ignore.
            pass
    # OSError covers many low-level network errors (e.g., socket errors).
    network_error_classes.append(OSError)

    is_network_error = False
    try:
        is_network_error = any(isinstance(error, cls) for cls in network_error_classes if cls is not None)
    except Exception:
        # If isinstance checks fail for some reason, fall back to string matching below.
        is_network_error = False

    error_str = str(error) if error is not None else ""
    if not is_network_error and isinstance(error_str, str) and "network is unreachable" in error_str.lower():
        is_network_error = True

    if is_network_error:
        # Log a warning without traceback to avoid leaking internal details, then raise a sanitized error.
        logger.warning("Network error detected while calling Responses API; marking as network unreachable.")
        raise RuntimeError("Network unreachable") from None

    error_context = (
        f" for input: {user_input[:MAX_ERROR_INPUT_SNIPPET]}..."
        if user_input and len(user_input) > MAX_ERROR_INPUT_SNIPPET
        else f" for input: {user_input}"
        if user_input
        else ""
    )

    if "rate limit" in str(error).lower():
        error_msg = f"Responses API rate limit exceeded{error_context}. Please try again later."
        logger.error(f"Rate limit error: {error}", exc_info=True)
    elif "authentication" in str(error).lower() or "unauthorized" in str(error).lower():
        error_msg = f"Responses API authentication failed{error_context}. Please check your API credentials."
        logger.error(f"Authentication error: {error}", exc_info=True)
    elif "quota" in str(error).lower() or "billing" in str(error).lower():
        error_msg = f"Responses API quota exceeded{error_context}. Please check your account status."
        logger.error(f"Quota error: {error}", exc_info=True)
    elif "timeout" in str(error).lower():
        error_msg = f"Responses API request timed out{error_context}. Please try again."
        logger.error(f"Timeout error: {error}", exc_info=True)
    elif getattr(error, "code", None) == "context_length_exceeded" or "context_length_exceeded" in str(error).lower():
        error_msg = (
            f"Responses API request exceeded the model context window{error_context}. "
            "Please shorten the conversation, reduce tool output, retry with compacted history, or try again with a smaller request."
        )
        logger.error(f"Context length error: {error}", exc_info=True)
    else:
        error_msg = f"Responses API error{error_context}: {str(error)}"
        logger.error(f"General responses API error: {error}", exc_info=True)

    return None, error_msg


def apply_usage_delta(usage: Any, previous_total: Optional[Union[int, float]] = None) -> Tuple[Optional[int], int]:
    """Apply a usage update by computing the delta and updating token counters.

    Args:
        usage: The usage payload as a dict, object, number, or string.
        previous_total: Optional previous total count to compute a delta against.

    Returns:
        A tuple of ``(current_total_or_none, delta_int)``.

    Raises:
        ValueError: If ``usage`` cannot be coerced to a token count.
    """
    current = safe_extract_total_tokens(usage)
    delta = compute_token_delta(current, previous_total)

    if delta > 0:
        try:
            from monitor.lib import token_management

            token_management.update_token_usage(delta)
        except Exception:
            logger.exception("apply_usage_delta: update_token_usage failed")

        if rate_limiter is not None:
            candidate_names = (
                "add_usage",
                "add_tokens",
                "consume",
                "consume_tokens",
                "record_usage",
                "record",
            )
            for name in candidate_names:
                fn = getattr(rate_limiter, name, None)
                if callable(fn):
                    try:
                        fn(delta)
                        break
                    except Exception:
                        logger.debug(
                            "apply_usage_delta: rate_limiter.%s failed",
                            name,
                            exc_info=True,
                        )

    try:
        if delta > 0:
            setattr(config, "CANONICAL_TOKEN_USAGE", current)
    except Exception:
        logger.debug(
            "apply_usage_delta: unable to set config.CANONICAL_TOKEN_USAGE",
            exc_info=True,
        )

    return current, delta
