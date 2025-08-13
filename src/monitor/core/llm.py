import logging
import litellm
import re

from monitor import config

logger = logging.getLogger(__name__)

from monitor.core.tooling import handle_tool_call, handle
from monitor.core.tools import TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS
from monitor.lib import rate_limiter

from monitor.lib.message_utils import prepare_messages_with_cache_control, normalize_message, sanitize_messages
from monitor.lib.preferences import PREFERENCE_PROMPT
from monitor.lib.tool_loading import function_descriptions
from monitor.lib.text_to_speech import TextToSpeech
from monitor.lib.history import append_to_history_with_count, generate_conversation_summary, reset_conversation_with_summary
from monitor.lib.token_management import count_message_tokens, update_token_usage
from monitor.lib.system_prompt import SYSTEM_PROMPT

TTS = TextToSpeech()           # Configure with preferred voice if needed

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

def get_llm_completion(log_prefix='', error_message='Error during litellm completion'):
    """Common logic for getting completion from LLM with error handling and rate limiting.
    Token counting and updates use canonical helpers from monitor.lib/token_management.py.
    """
    try:
        summarization_attempted = False
        # Build conversation messages
        messages = prepare_messages_with_cache_control(config.CONVERSATION_HISTORY, config.MODEL)
        preferences = PREFERENCE_PROMPT
        if preferences:
            # Prepend user preferences as a system message (always check latest state)
            messages = [{"role": "system", "content": preferences}] + messages

        # Sanitize messages before counting, validation, and sending
        messages = sanitize_messages(messages)

        # Estimate token count for the conversation history using canonical helper
        estimated_tokens = 0
        for msg in messages:
            normalized_msg = normalize_message(msg)
            estimated_tokens += count_message_tokens(normalized_msg)

        # Preflight validation before rate limiting and request sizing
        try:
            validate_tool_message_order(messages)
        except ValueError as ve:
            logger.error(f"Message validation failed (pre-wait): {ve}")
            return None, str(ve)

        estimated_request = estimated_tokens + (
           config.REASONING_MAX_COMPLETION_TOKENS
           if config.REASONING_MODEL_PREFIX.lower() in config.MODEL.lower()
           else 0
        )

        if estimated_request > config.MODEL_MAX_TPM:
            if getattr(config, "ENABLE_AUTO_SUMMARIZE_ON_LIMIT", False) and not summarization_attempted:
                logger.info("Attempting auto-summarization due to token limit...")
                try:
                    summary_response = generate_conversation_summary(
                        SYSTEM_PROMPT,
                        config.CONVERSATION_HISTORY,
                        config.SUMMARIZATION_CONFIG,
                        config.MODEL,
                        litellm.completion,
                        count_message_tokens,
                        rate_limiter.RATE_LIMITER,
                        logger,
                        config
                    )
                    summary_content = None
                    try:
                        response_attr = dict_to_attr(summary_response)
                        if (
                            hasattr(response_attr, "choices")
                            and response_attr.choices
                            and len(response_attr.choices) > 0
                            and hasattr(response_attr.choices[0], "message")
                            and response_attr.choices[0].message
                            and hasattr(response_attr.choices[0].message, "content")
                        ):
                            summary_content = response_attr.choices[0].message.content
                    except Exception:
                        pass

                    last_user_content = ""
                    for m in reversed(config.CONVERSATION_HISTORY):
                        if m.get("role") == "user":
                            last_user_content = m.get("content", "")
                            break

                    reset_conversation_with_summary(
                        summary_content or "",
                        SYSTEM_PROMPT,
                        last_user_content,
                        config.CONVERSATION_HISTORY,
                        append_to_history_with_count,
                        logger,
                        config
                    )
                    summarization_attempted = True

                    messages = prepare_messages_with_cache_control(config.CONVERSATION_HISTORY, config.MODEL)
                    if preferences:
                        messages = [{"role": "system", "content": preferences}] + messages
                    messages = sanitize_messages(messages)
                    estimated_tokens = 0
                    for msg in messages:
                        normalized_msg = normalize_message(msg)
                        estimated_tokens += count_message_tokens(normalized_msg)
                    # Validate again after messages are rebuilt
                    try:
                        validate_tool_message_order(messages)
                    except ValueError as ve:
                        logger.error(f"Message validation failed after summarization (token limit path): {ve}")
                        return None, str(ve)
                    estimated_request = estimated_tokens + (
                        config.REASONING_MAX_COMPLETION_TOKENS
                        if config.REASONING_MODEL_PREFIX.lower() in config.MODEL.lower()
                        else 0
                    )
                    logger.info("Auto-summarization complete; retrying request.")
                except Exception as se:
                    logger.error(f"Auto-summarization failed: {se}", exc_info=True)

        if estimated_request > config.MODEL_MAX_TPM:
            return None, (
                f"Input too large: {estimated_request} tokens "
                f"vs model limit {config.MODEL_MAX_TPM}. Cannot send request."
                "Please reduce the size of your input (file, diff, or message) or send smaller requests."
            ), 

        # Validate before waiting on rate limiter
        try:
            validate_tool_message_order(messages)
        except ValueError as ve:
            logger.error(f"Message validation failed (before rate limit wait): {ve}")
            return None, str(ve)

        wait_result = rate_limiter.RATE_LIMITER.wait_if_needed(estimated_request)
        if wait_result is None:
            if getattr(config, "ENABLE_AUTO_SUMMARIZE_ON_LIMIT", False) and not summarization_attempted:
                logger.info("Attempting auto-summarization due to rate limit safety threshold...")
                try:
                    summary_response = generate_conversation_summary(
                        SYSTEM_PROMPT,
                        config.CONVERSATION_HISTORY,
                        config.SUMMARIZATION_CONFIG,
                        config.MODEL,
                        litellm.completion,
                        count_message_tokens,
                        rate_limiter.RATE_LIMITER,
                        logger,
                        config
                    )
                    summary_content = None
                    try:
                        response_attr = dict_to_attr(summary_response)
                        if (
                            hasattr(response_attr, "choices")
                            and response_attr.choices
                            and len(response_attr.choices) > 0
                            and hasattr(response_attr.choices[0], "message")
                            and response_attr.choices[0].message
                            and hasattr(response_attr.choices[0].message, "content")
                        ):
                            summary_content = response_attr.choices[0].message.content
                    except Exception:
                        pass

                    last_user_content = ""
                    for m in reversed(config.CONVERSATION_HISTORY):
                        if m.get("role") == "user":
                            last_user_content = m.get("content", "")
                            break

                    reset_conversation_with_summary(
                        summary_content or "",
                        SYSTEM_PROMPT,
                        last_user_content,
                        config.CONVERSATION_HISTORY,
                        append_to_history_with_count,
                        logger,
                        config
                    )
                    summarization_attempted = True

                    messages = prepare_messages_with_cache_control(config.CONVERSATION_HISTORY, config.MODEL)
                    if preferences:
                        messages = [{"role": "system", "content": preferences}] + messages
                    messages = sanitize_messages(messages)
                    estimated_tokens = 0
                    for msg in messages:
                        normalized_msg = normalize_message(msg)
                        estimated_tokens += count_message_tokens(normalized_msg)
                    estimated_request = estimated_tokens + (
                        config.REASONING_MAX_COMPLETION_TOKENS
                        if config.REASONING_MODEL_PREFIX.lower() in config.MODEL.lower()
                        else 0
                    )
                    # Validate after rebuilding messages in rate limit summarization path
                    try:
                        validate_tool_message_order(messages)
                    except ValueError as ve:
                        logger.error(f"Message validation failed after summarization (rate limit path): {ve}")
                        return None, str(ve)
                    logger.info("Auto-summarization complete; retrying request.")
                except Exception as se:
                    logger.error(f"Auto-summarization failed: {se}", exc_info=True)

                # Validate before attempting the second wait
                try:
                    validate_tool_message_order(messages)
                except ValueError as ve:
                    logger.error(f"Message validation failed (before second rate limit wait): {ve}")
                    return None, str(ve)

                wait_result = rate_limiter.RATE_LIMITER.wait_if_needed(estimated_request)

            if wait_result is None:
                return None, (
                    f"Input too large: {estimated_request} tokens. Model limit {config.MODEL_MAX_TPM} tokens."
                    "Reduce the size of your request."
                ), 

        # Final validation just before making the completion call
        try:
            validate_tool_message_order(messages)
        except ValueError as ve:
            logger.error(f"Message validation failed (pre-completion): {ve}")
            return None, str(ve)

        response = call_litellm_completion(config.MODEL, messages)

        # Convert response (and possibly inner objects) to attribute-access-friendly structures
        response = dict_to_attr(response)

        # Record actual usage using canonical update
        update_token_usage(response if hasattr(response, 'usage') and hasattr(response.usage, 'total_tokens') else estimated_tokens)

        actual_used = (
           response.usage.total_tokens
           if hasattr(response, "usage") and hasattr(response, "usage") and hasattr(response.usage, "total_tokens")
           else estimated_tokens
        )
        rate_limiter.RATE_LIMITER.add_request(actual_used)

        logger.debug(f"{log_prefix} Received response from the language model.")
        return response, None
    except Exception as e:
        error_msg = f"{error_message}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg


def process_direct_response(response_message):
    """Process a direct (non-function-call) response from LLM"""
    logger.debug("Processing direct LLM response...")
    assistant_message = normalize_message(response_message)
    assistant_content = assistant_message.get("content", "")
    
    # Log and update conversation history
    if (config.CONVERSATION_LOG_FILE and not config.CONVERSATION_LOG_FILE.closed):
        config.CONVERSATION_LOG_FILE.write(f"AI: {assistant_content}\n")
    append_to_history_with_count(
        assistant_message,
        config.CONVERSATION_HISTORY,
        count_message_tokens,
        update_token_usage
    )
    
    if config.LAST_INPUT_WAS_VOICE:
        TTS.speak(assistant_content)
        config.LAST_INPUT_WAS_VOICE = False

    return assistant_content

def process_response_by_type(response_type, response, response_message):
    """Route the response to appropriate handler based on type"""
    logger.debug(f"Handling response of type: {response_type}")
    
    if response_type == "tool_call":
        return handle_tool_call(response)
    elif response_type == "function_call":
        return handle(response_message.function_call)
    else:
        return process_direct_response(response_message)

def determine_response_type(response_message):
    """Determine the type of response and how to handle it"""
    logger.debug("Determining response type...")
    
    if hasattr(response_message, 'tool_calls') and response_message.tool_calls and len(response_message.tool_calls) > 0:
        return "tool_call"
    elif hasattr(response_message, 'function_call') and response_message.function_call:
        return "function_call"
    else:
        return "direct"


def get_llm_initial_completion():
    """Get initial response from LLM for the query with rate limiting"""
    logger.debug("Getting initial LLM response...")
    return get_llm_completion(
        log_prefix="Initial request:",
        error_message="I apologize, but I encountered an error processing your request. Please try again"
    )

def extract_tool_calls(response):
    """Extract and validate tool calls from LLM response"""
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
            config.CONVERSATION_LOG_FILE.write(f"AI: {assistant_content}\n")
        
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
    model name contains 'openai/o3'.
    
    Args:
        model: The full model identifier, e.g. 'openai/o3-2025-04-16'
        messages: The list of chat messages for the request.

    Returns:
        The litellm completion response.
    """
    # Base kwargs common to all models
    kwargs = {
        "model": model,
        "messages": messages,
        "tools": function_descriptions(
            TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, model
        ),
        "drop_params":True
    }
    
    pattern = re.compile(re.escape(config.REASONING_MODEL_PREFIX), re.IGNORECASE)  
    if pattern.search(model):
        kwargs.update(
            reasoning_effort=config.REASONING_EFFORT,
            max_completion_tokens=config.REASONING_MAX_COMPLETION_TOKENS,
        )
    
    return litellm.completion(**kwargs)
