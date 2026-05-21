"""
Message utilities for handling conversation history and message formatting.
This module provides utilities for formatting messages for different LLM providers,
including special handling for Anthropic's ephemeral caching mechanism.
"""

import logging
import re
import json

logger = logging.getLogger(__name__) 

def normalize_message(msg):
    """
    Normalize various message-like inputs into a standard dictionary with at least
    'role' and 'content' keys. Preserves extra keys for dict inputs and maps certain
    attributes for object-like inputs.

    Behavior:
    - If input is a dict: copy it; ensure 'role' exists (default 'assistant' if missing),
      ensure 'content' exists (default ''), coerce 'content' to str if not None/str.
      Also preserves 'tool_calls' when present.
    - If input has attributes 'content' and optional 'role': build a dict
      {'role': getattr(msg,'role','assistant'), 'content': str(getattr(msg,'content',''))}.
      If it has 'tool_call_id' or 'name' attributes, include them. If it has 'function_call',
      include it as 'function_call'. If it has 'tool_calls', normalize them into a list of dicts
      with keys: 'id', 'type' (default 'function'), and 'function' containing 'name' and
      'arguments' (arguments serialized to string via JSON when not already a string).
    - If input is a str: return {'role': 'assistant', 'content': input}.
    - Else: coerce to str content with default role 'assistant'.

    Args:
        msg: The message-like object to normalize.

    Returns:
        dict: Normalized message dictionary with at least 'role' and 'content'.
    """
    logger.debug("Entering normalize_message with input type=%s", type(msg).__name__)
    try:
        allowed_roles = {'system', 'user', 'assistant', 'tool', 'function'}
        def _normalize_role(role_val):
            try:
                if isinstance(role_val, str):
                    r = role_val.strip().lower()
                    if r in allowed_roles:
                        return r
                    logger.debug("Unknown role string '%s'; coercing to 'assistant'", role_val)
                    return 'assistant'
                if role_val is None:
                    return 'assistant'
                logger.debug("Non-string role of type %s encountered; coercing to 'assistant'", type(role_val).__name__)
                return 'assistant'
            except Exception as e:
                logger.error("Error normalizing role value %r: %s; defaulting to 'assistant'", role_val, str(e), exc_info=True)
                return 'assistant'

        if isinstance(msg, dict):
            logger.debug("Normalizing message from dict input")
            out = msg.copy()
            if 'role' not in out or out.get('role') is None:
                logger.debug("Input dict missing role; defaulting to 'assistant'")
                out['role'] = 'assistant'
            # Coerce/validate role strictly
            original_role = out.get('role')
            normalized_role = _normalize_role(original_role)
            if original_role != normalized_role:
                logger.debug("Coerced role from %r to %r in dict input", original_role, normalized_role)
            out['role'] = normalized_role
            if 'content' not in out:
                logger.debug("Input dict missing content; defaulting to empty string")
                out['content'] = ''
            else:
                value = out.get('content')
                if value is None:
                    logger.debug("Input dict content is None; coercing to empty string")
                    out['content'] = ''
                elif not isinstance(value, str):
                    try:
                        out['content'] = str(value)
                        logger.debug("Coerced dict content to string via str()")
                    except Exception as e:
                        logger.error("Error coercing dict content to string: %s", str(e), exc_info=True)
                        out['content'] = ''
            # Remove tool_calls if falsy; keep only on assistant messages
            try:
                if 'tool_calls' in out and not out.get('tool_calls'):
                    logger.debug("Input dict has falsy tool_calls; removing key")
                    del out['tool_calls']
                elif out.get('role') != 'assistant' and 'tool_calls' in out:
                    logger.debug("Input dict role is %s; removing tool_calls from non-assistant message", out.get('role'))
                    del out['tool_calls']
            except Exception as e:
                logger.error("Error sanitizing tool_calls in dict input: %s", str(e), exc_info=True)
            return out

        if hasattr(msg, 'content'):
            logger.debug("Normalizing message from attribute-based input")
            raw_role = getattr(msg, 'role', None)
            role = _normalize_role(raw_role)
            if raw_role != role:
                logger.debug("Coerced attribute-based role from %r to %r", raw_role, role)
            content = str(getattr(msg, 'content', ''))
            out = {
                'role': role if role is not None else 'assistant',
                'content': content
            }
            if hasattr(msg, 'tool_call_id'):
                out['tool_call_id'] = getattr(msg, 'tool_call_id')
            if hasattr(msg, 'name'):
                out['name'] = getattr(msg, 'name')
            if hasattr(msg, 'function_call'):
                out['function_call'] = getattr(msg, 'function_call')
            if hasattr(msg, 'tool_calls'):
                logger.debug("Attribute-based input has tool_calls; attempting to normalize")
                raw_tool_calls = getattr(msg, 'tool_calls', None)
                normalized_tool_calls = []
                try:
                    iterable_tool_calls = list(raw_tool_calls) if raw_tool_calls is not None else []
                except Exception:
                    iterable_tool_calls = [raw_tool_calls] if raw_tool_calls is not None else []
                for idx, tc in enumerate(iterable_tool_calls):
                    try:
                        def _get(obj, key, default=None):
                            try:
                                if isinstance(obj, dict):
                                    return obj.get(key, default)
                                if hasattr(obj, key):
                                    return getattr(obj, key, default)
                                try:
                                    return obj[key]
                                except Exception:
                                    return default
                            except Exception:
                                return default
                        tc_id = _get(tc, 'id', None)
                        tc_type = _get(tc, 'type', None) or 'function'
                        func_block = _get(tc, 'function', None)
                        func_name = None
                        func_args = None
                        if func_block is not None:
                            if isinstance(func_block, dict):
                                func_name = func_block.get('name')
                                func_args = func_block.get('arguments')
                            else:
                                func_name = getattr(func_block, 'name', None)
                                func_args = getattr(func_block, 'arguments', None)
                        else:
                            func_name = _get(tc, 'name', None)
                            func_args = _get(tc, 'arguments', None)
                        if func_args is not None and not isinstance(func_args, str):
                            try:
                                func_args = json.dumps(func_args, ensure_ascii=False)
                                logger.debug("Serialized tool_call arguments to JSON for index %s", idx)
                            except Exception as ser_e:
                                logger.debug("Failed to JSON-serialize tool_call arguments at index %s: %s; falling back to str()", idx, str(ser_e))
                                try:
                                    func_args = str(func_args)
                                except Exception:
                                    func_args = ''
                        normalized_tool_calls.append({
                            'id': tc_id,
                            'type': tc_type,
                            'function': {
                                'name': func_name,
                                'arguments': func_args
                            }
                        })
                    except Exception as e:
                        logger.error("Failed to normalize tool_call at index %s: %s", idx, str(e), exc_info=True)
                        try:
                            fallback_arguments = str(tc)
                        except Exception:
                            fallback_arguments = ''
                        normalized_tool_calls.append({
                            'id': None,
                            'type': 'function',
                            'function': {
                                'name': None,
                                'arguments': fallback_arguments
                            }
                        })
                if len(normalized_tool_calls) > 0:
                    out['tool_calls'] = normalized_tool_calls
                logger.debug("Normalized %s tool_calls", len(normalized_tool_calls))
            logger.debug("Attribute-based message normalized with keys: %s", list(out.keys()))
            return out

        if isinstance(msg, str):
            logger.debug("Normalizing message from string input with default role 'assistant'")
            return {'role': 'assistant', 'content': msg}

        logger.debug("Normalizing message from unsupported type; coercing to string with default role 'assistant'")
        return {'role': 'assistant', 'content': str(msg)}
    except Exception as e:
        logger.error("Error normalizing message of type %s: %s", type(msg).__name__, str(e), exc_info=True)
        try:
            return {'role': 'assistant', 'content': str(msg)}
        except Exception:
            return {'role': 'assistant', 'content': ''}

def sanitize_messages(messages):
    """
    Sanitize a list of messages to ensure proper structure and constraints.

    Behavior:
    - Normalizes each message using normalize_message.
    - Removes 'tool_calls' when it's an empty list or otherwise falsy.
    - Ensures 'tool' role messages have no 'tool_calls' and include a 'tool_call_id'.
    - Ensures non-assistant roles do not include a 'tool_calls' field.

    Args:
        messages (list): List of message-like objects.

    Returns:
        list: Sanitized list of message dictionaries.
    """
    try:
        msg_count = len(messages)
    except Exception:
        msg_count = 1 if messages is not None else 0
    logger.debug("Entering sanitize_messages with message_count=%s", msg_count)

    try:
        iterable = list(messages) if messages is not None else []
    except Exception:
        iterable = [messages] if messages is not None else []

    sanitized = []
    for idx, m in enumerate(iterable):
        try:
            nm = normalize_message(m)
        except Exception as e:
            logger.error("Error normalizing message at index %s: %s", idx, str(e), exc_info=True)
            try:
                nm = {'role': 'assistant', 'content': str(m)}
            except Exception:
                nm = {'role': 'assistant', 'content': ''}

        # Remove empty or falsy tool_calls
        try:
            if 'tool_calls' in nm and not nm.get('tool_calls'):
                logger.debug("Removing falsy tool_calls from message at index %s", idx)
                del nm['tool_calls']
        except Exception as e:
            logger.debug("Error checking/removing tool_calls at index %s: %s", idx, str(e), exc_info=True)

        role = nm.get('role', 'assistant')

        # Ensure non-assistant roles do not carry tool_calls
        if role != 'assistant' and 'tool_calls' in nm:
            logger.debug("Removing tool_calls from non-assistant message at index %s with role=%s", idx, role)
            try:
                del nm['tool_calls']
            except Exception as e:
                logger.debug("Failed to remove tool_calls from message at index %s: %s", idx, str(e), exc_info=True)

        # Ensure 'tool' role messages have no 'tool_calls' and require 'tool_call_id'
        if role == 'tool':
            if 'tool_calls' in nm:
                logger.debug("Removing tool_calls from tool role message at index %s", idx)
                try:
                    del nm['tool_calls']
                except Exception as e:
                    logger.debug("Failed to remove tool_calls from tool message at index %s: %s", idx, str(e), exc_info=True)
            if 'tool_call_id' not in nm:
                logger.debug("tool role message at index %s missing tool_call_id; adding empty placeholder", idx)
                nm['tool_call_id'] = ''

        sanitized.append(nm)

    logger.debug("Sanitized %s messages", len(sanitized))
    return sanitized

def is_anthropic_model(model_name):
    """
    Determine if the specified model is from Anthropic.
    
    Args:
        model_name (str): The model name to check
        
    Returns:
        bool: True if the model is from Anthropic, False otherwise
    """
    logger.debug("Entering is_anthropic_model with model_name=%s", model_name)
    
    anthropic_patterns = [
        r'^anthropic/', 
        r'^claude', 
        r'^claude-', 
        r'^claude\d'
    ]
    
    for pattern in anthropic_patterns:
        if re.match(pattern, model_name.lower()):
            logger.debug("Model %s matched Anthropic pattern %s", model_name, pattern)
            return True
    
    logger.debug("Model %s is not an Anthropic model", model_name)
    return False

def prepare_messages_with_cache_control(messages, model_name):
    """
    Prepare messages with cache_control for Anthropic models to enable efficient caching.

    C-2: removed the ``disable_for_tool_calls`` parameter. It was never invoked
    as True by any caller, and its substring-match heuristic
    (``msg.content.lower().find('tool')``) would have produced false positives
    on virtually any coding conversation that mentions tools or functions —
    silently disabling caching at the worst possible time. If tool-call-aware
    cache invalidation is ever needed, design it around the message ``role``
    and ``tool_calls`` fields, not substring search.

    Args:
        messages (list): List of message dictionaries
        model_name (str): The name of the model being used

    Returns:
        list: Properly formatted messages with cache_control parameters if applicable
    """
    logger.debug(
        "Entering prepare_messages_with_cache_control with model_name=%s, message_count=%s",
        model_name, len(messages),
    )

    if not is_anthropic_model(model_name):
        logger.debug("Skipping cache control - %s is not an Anthropic model", model_name)
        return messages

    logger.info("Preparing messages with cache control for Anthropic model %s", model_name)

    # Create a new list with shallow copies of each message dict to avoid mutating the original messages.
    # This ensures we don't accidentally modify shared references (e.g., top-level dicts) while preserving
    # nested structures like tool_calls; we don't deep-copy tool_calls because we never mutate them here.
    prepared_messages = [m.copy() if isinstance(m, dict) else m for m in messages]
    logger.debug("Created copy of messages for modification")
    
    # Add cache_control to system message if it exists
    system_modified = False
    for i, message in enumerate(prepared_messages):
        if message.get('role') == 'system':
            try:
                # Create a new message with cache_control
                system_message = message.copy()
                system_message['cache_control'] = {'type': 'ephemeral'}
                prepared_messages[i] = system_message
                system_modified = True
                logger.debug("Added cache_control to system message at index %s", i)
                break
            except Exception as e:
                logger.error("Error adding cache_control to system message: %s", str(e), exc_info=True)
    
    if not system_modified:
        logger.debug("No system message found to modify")
    
    # Add cache_control to the final message if it's from the user
    if prepared_messages:
        try:
            if prepared_messages[-1].get('role') == 'user':
                final_message = prepared_messages[-1].copy()
                final_message['cache_control'] = {'type': 'ephemeral'}
                prepared_messages[-1] = final_message
                logger.debug("Added cache_control to final user message at index %s", len(prepared_messages) - 1)
            else:
                logger.debug("Final message is not from user, role=%s", prepared_messages[-1].get('role'))
        except Exception as e:
            logger.error("Error adding cache_control to final user message: %s", str(e), exc_info=True)
    else:
        logger.debug("Message list is empty, no final message to modify")
    
    logger.info("Successfully prepared %s messages with cache control", len(prepared_messages))
    return prepared_messages
