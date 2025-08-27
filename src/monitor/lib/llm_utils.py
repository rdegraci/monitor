"""Utility helpers for LLM processing moved out of core/llm.py for reuse and clarity.

This module contains lightweight helpers and adapters that the core llm orchestration
imports. It intentionally mirrors the behavior in src/monitor/core/llm.py at the time
of extraction; any future refactorings should update both caller sites as needed.
"""

import logging
import re
import litellm

from monitor import config
from monitor.core.tools import TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS
from monitor.lib.tool_loading import function_descriptions
from monitor.lib.message_utils import normalize_message, sanitize_messages
from monitor.lib.history import append_to_history_with_count
from monitor.lib.token_management import count_message_tokens, update_token_usage
from monitor.lib.text_to_speech import TextToSpeech

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
    logger.debug("Processing direct LLM response...")
    assistant_message = normalize_message(response_message)
    assistant_content = assistant_message.get("content", "")

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
    # Defensive check for choices
    if not getattr(response, "choices", None) or len(response.choices) == 0:
        raise ValueError("Malformed response: missing choices for tool extraction")

    msg = response.choices[0].message
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
        logger.debug(f"Unable to evaluate tool_call id presence: {e}")
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
                        rebuilt_tool_calls.append(dict(tc))
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
        logger.debug(f"sanitize_messages failed in extract_tool_calls: {e}")
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
    # Defensive check
    if not getattr(response, "choices", None) or len(response.choices) == 0:
        raise ValueError("Malformed response: missing choices when processing finish reason")

    finish_reason = response.choices[0].finish_reason

    if finish_reason == "refusal":
        logger.error("The request was refused due to policy violations.")
        # Remove the last turn (user input and any assistant response) from conversation history
        if len(config.CONVERSATION_HISTORY) >= 1:
            # Remove the last user message that caused the refusal
            last_message = config.CONVERSATION_HISTORY[-1]
            if last_message.get('role') == 'user':
                config.CONVERSATION_HISTORY.pop()
                logger.debug("Removed user message that caused refusal from conversation history")

            # If there's an assistant message that was also added, remove it too
            if len(config.CONVERSATION_HISTORY) >= 1:
                second_last_message = config.CONVERSATION_HISTORY[-1]
                if second_last_message.get('role') == 'assistant':
                    config.CONVERSATION_HISTORY.pop()
                    logger.debug("Removed assistant message from conversation history due to refusal")

        return "Request was refused."

    if finish_reason == "length":
        logger.error("The conversation was too long for the context window.")
        return "Length too long."

    if finish_reason == "content_filter":
        logger.error("The content was filtered due to policy violations.")
        return "Content filtered."

    if finish_reason == "tool_calls":
        return None  # Indicate need for another tool call

    if finish_reason == "stop":
        assistant_content = response.choices[0].message.content
        if (config.CONVERSATION_LOG_FILE and not config.CONVERSATION_LOG_FILE.closed):
            try:
                config.CONVERSATION_LOG_FILE.write(f"AI: {assistant_content}\n")
            except Exception:
                logger.exception("Failed writing assistant content to conversation log file")

        if assistant_content is None:
            return "Ok."
        return assistant_content

    if "xai/grok" in config.MODEL and finish_reason == "":
        return None  # Indicate need for another tool call

    logger.error(f"Unexpected finish_reason: {finish_reason} - {response.choices[0]}")
    return f"Unexpected finish reason: {finish_reason}"


def call_litellm_completion(model: str, messages: list):
    """
    Wrapper that adds `reasoning_effort` and `max_completion_tokens` when the
    model name contains the configured reasoning model prefix.

    Args:
        model: The full model identifier, e.g. 'openai/o3-2025-04-16'
        messages: The list of chat messages for the request.

    Returns:
        The litellm completion response.
    """
    kwargs = {
        "model": model,
        "messages": messages,
        "tools": function_descriptions(
            TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, model
        ),
        "drop_params": True,
    }

    pattern = re.compile(re.escape(config.REASONING_MODEL_PREFIX), re.IGNORECASE)
    if pattern.search(model):
        kwargs.update(
            reasoning_effort=config.REASONING_EFFORT,
            max_completion_tokens=config.REASONING_MAX_COMPLETION_TOKENS,
        )

    return litellm.completion(**kwargs)
