import logging
import json
from openai import OpenAI

from monitor import config
from monitor.core.tools import TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS
from monitor.core.tooling import execute_tool_call
from monitor.lib.message_utils import normalize_message, sanitize_messages
from monitor.lib.token_management import count_message_tokens, update_token_usage
from monitor.lib import rate_limiter
from monitor.lib.llm_utils import dict_to_attr, validate_tool_message_order
from monitor.lib.tool_loading import function_descriptions

logger = logging.getLogger(__name__)

client=None 

def strip_openai_prefix(model_name):
    """Remove a leading 'openai/' prefix from a model name, case-insensitively.

    Args:
        model_name (str or None): The model name to normalize.

    Returns:
        str or original value: The model name with a leading 'openai/' removed
        if present (case-insensitive). If model_name is falsy or not a str,
        returns model_name unchanged.

    Examples:
        >>> strip_openai_prefix("openai/gpt-4")
        'gpt-4'
        >>> strip_openai_prefix("OpenAI/GPT-4o")
        'GPT-4o'
        >>> strip_openai_prefix(None) is None
        True
        >>> strip_openai_prefix(123)
        123
    """
    if not model_name or not isinstance(model_name, str):
        return model_name
    lower = model_name.lower()
    prefix = "openai/"
    if lower.startswith(prefix):
        return model_name[len(prefix):]
    return model_name


def normalize_tool_descriptors(tool_list):
    """Normalize a list of tool descriptor dicts into a flat, consistent shape.

    The function accepts tool descriptor entries in one of two common shapes:
      1) Flat descriptors:
         { 'type': 'function', 'name': 'foo', 'description': '...', 'parameters': { ... } }
      2) Nested descriptors:
         { 'type': 'function', 'function': { 'name': 'foo', 'description': '...', 'parameters': {...} } }

    Returns a new list where each descriptor is a dict with at minimum:
      { 'type': 'function', 'name': <str>, 'description': <str>, 'parameters': {
            'type': 'object', 'properties': {...}, 'required': [...] (if present)
        }
      }

    Defensive behavior:
    - Skips non-dict entries.
    - Skips entries without a valid string 'name'.
    - Ensures 'parameters' is a dict; sets parameters['type'] == 'object'.
    - Ensures parameters['properties'] exists as a dict.
    - If 'required' exists, ensures it's a list (or converts/cleans to an empty list).
    - Logs exceptions per-entry but continues processing other entries.
    """
    if not tool_list:
        return tool_list

    normalized = []
    for idx, entry in enumerate(tool_list):
        try:
            if not isinstance(entry, dict):
                logger.debug(f"Skipping non-dict tool descriptor at index {idx}: {type(entry)}")
                continue

            # Support nested 'function' wrapper
            nested = entry.get('function') if isinstance(entry.get('function'), dict) else None

            # Derive core fields with nested taking precedence
            name = None
            description = None
            parameters = None
            type_val = None

            if nested:
                name = nested.get('name') or entry.get('name')
                description = nested.get('description') or entry.get('description') or ""
                parameters = nested.get('parameters') or entry.get('parameters')
                type_val = entry.get('type') or nested.get('type') or "function"
            else:
                name = entry.get('name')
                description = entry.get('description') or entry.get('doc') or ""
                parameters = entry.get('parameters')
                type_val = entry.get('type') or "function"

            # Validate name
            if not name or not isinstance(name, str):
                logger.debug(f"Skipping tool descriptor without valid name at index {idx}: {name}")
                continue

            # Ensure parameters is a dict
            if not isinstance(parameters, dict):
                parameters = {}

            # Work on a shallow copy to avoid mutating original
            parameters = dict(parameters)

            # Ensure parameters['type'] == 'object'
            if parameters.get('type') != 'object':
                parameters['type'] = 'object'

            # Ensure properties exists as a dict
            props = parameters.get('properties')
            if not isinstance(props, dict):
                parameters['properties'] = {}

            # Ensure 'required' is a list if present; coerce if possible
            if 'required' in parameters:
                req = parameters.get('required')
                if isinstance(req, list):
                    # fine
                    pass
                elif hasattr(req, '__iter__') and not isinstance(req, (str, bytes, dict)):
                    try:
                        parameters['required'] = list(req)
                    except Exception:
                        parameters['required'] = []
                else:
                    parameters['required'] = []

            normalized.append({
                'type': type_val,
                'name': name,
                'description': description or "",
                'parameters': parameters
            })

        except Exception as e:
            logger.exception(f"Error normalizing tool descriptor at index {idx}: {e}")
            # Continue processing other entries despite the error
            continue

    return normalized


def configure_responses_adapter():
    global client
    client = OpenAI()


def validate_responses_config():
    """Validate that required responses API configuration is present."""
    required_configs = ['MODEL', 'RESPONSES_API']
    missing_configs = []
    
    for config_name in required_configs:
        if not hasattr(config, config_name) or not getattr(config, config_name):
            missing_configs.append(config_name)
    
    if missing_configs:
        raise ValueError(f"Missing required responses API configuration: {missing_configs}")
    
    logger.debug("Responses API configuration validated successfully")


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
            messages.append({"role": "system", "content": PREFERENCE_PROMPT})
        
        # Add the user input
        messages.append({"role": "user", "content": user_input})
        
        # Sanitize messages before sending
        messages = sanitize_messages(messages)
        
        logger.debug(f"Prepared {len(messages)} messages for responses API")
        return messages
        
    except Exception as e:
        logger.error(f"Error preparing response messages: {e}", exc_info=True)
        raise


def estimate_response_tokens(messages):
    """Estimate token count for responses API messages."""
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


def get_tools_for_model():
    """Get appropriate tool definitions based on the model type.
    
    Returns:
        tuple: (tools, tool_choice) where tools is the tool definitions and 
               tool_choice is the tool selection strategy
    """
    try:
        model_lower = config.MODEL.lower()
        
        # Check if tools are disabled
        if getattr(config, 'DISABLE_TOOLS', False):
            logger.debug("Tools disabled by configuration")
            return None, None
        
        # Determine which tools to use based on model
        if "gemini" in model_lower:
            tools = GEMINI_TOOL_DESCRIPTIONS
            logger.debug(f"Using Gemini tool descriptions ({len(tools) if tools else 0} tools)")
        else:
            tools = function_descriptions(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, model_lower)
            logger.debug(f"Using function descriptions ({len(tools) if tools else 0} tools)")
        
        # Normalize tool descriptors to a consistent flat shape for downstream usage
        if tools:
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


def call_responses_api(messages):
    """Make the actual call to the responses API via OpenAI Responses API.
    
    Args:
        messages (list): Prepared messages for the API
        
    Returns:
        dict: Normalized response wrapper suitable for convert_response_format
        
    Raises:
        Exception: Any API-related errors
    """
    try:
        logger.debug("Calling responses API via OpenAI client")
        
        # Get tools for the current model
        tools, tool_choice = get_tools_for_model()
        
        # Build request parameters, include only non-None values
        params = {'model': strip_openai_prefix(config.MODEL)}
        
        # Determine input: if a previous response id exists, send only the new user input
        if hasattr(config, 'RESPONSE_ID') and getattr(config, 'RESPONSE_ID'):
            params['previous_response_id'] = getattr(config, 'RESPONSE_ID')
            # Extract most recent user message content
            user_text = None
            try:
                for m in reversed(messages):
                    if isinstance(m, dict) and m.get('role') == 'user':
                        user_text = m.get('content')
                        break
            except Exception:
                user_text = None
            if not user_text:
                # Fallback: concatenate all message contents
                try:
                    user_text = " ".join(m.get('content', '') for m in messages if isinstance(m, dict))
                except Exception:
                    user_text = ""
            params['input'] = user_text
            logger.debug("Sending only the new user input alongside previous_response_id to OpenAI Responses API")
        else:
            # First-call: send prepared messages as input (may include system preferences)
            params['input'] = messages
            logger.debug("Sending prepared messages as input to OpenAI Responses API")
        
        # Add optional parameters only if present in config
        if getattr(config, 'TEMPERATURE', None) is not None:
            params['temperature'] = getattr(config, 'TEMPERATURE')
        if getattr(config, 'TOP_P', None) is not None:
            params['top_p'] = getattr(config, 'TOP_P')
        if getattr(config, 'FREQUENCY_PENALTY', None) is not None:
            params['frequency_penalty'] = getattr(config, 'FREQUENCY_PENALTY')
        if getattr(config, 'PRESENCE_PENALTY', None) is not None:
            params['presence_penalty'] = getattr(config, 'PRESENCE_PENALTY')
        
        max_output_tokens = getattr(config, 'MAX_COMPLETION_TOKENS', None)
        if max_output_tokens is not None:
            params['max_output_tokens'] = max_output_tokens
        
        # Add tools if available
        if tools:
            params['tools'] = tools
            params['tool_choice'] = tool_choice
            logger.debug(f"Added {len(tools)} tools to responses API call with choice '{tool_choice}'")
        else:
            logger.debug("No tools available for responses API call")
        
        # Call OpenAI Responses API (initial call)
        response = client.responses.create(**params)
        
        logger.debug("Successfully received response from OpenAI Responses API")
        
        # Persist response id into config if present
        try:
            resp_id = getattr(response, 'id', None)
            if resp_id:
                setattr(config, 'RESPONSE_ID', resp_id)
                logger.debug(f"Persisted response id {resp_id} into config.RESPONSE_ID")
        except Exception:
            logger.debug("Failed to persist response id to config, continuing")
        
        # Extract token usage (support common shapes) for the initial response
        actual_tokens = None
        try:
            usage = getattr(response, 'usage', None)
            if usage is None:
                actual_tokens = None
            else:
                # usage might be an object with attributes or a dict-like
                if isinstance(usage, dict):
                    actual_tokens = usage.get('total_tokens') or usage.get('total_token_count') or usage.get('total')
                else:
                    actual_tokens = getattr(usage, 'total_tokens', None) or getattr(usage, 'total_token_count', None) or getattr(usage, 'total', None)
        except Exception:
            actual_tokens = None
        
        # If actual_tokens is None, set to 0 to avoid None propagation
        if actual_tokens is None:
            actual_tokens = 0
        
        # Update token usage and rate limiter immediately for the initial response
        try:
            update_token_usage(actual_tokens)
            logger.debug(f"Updated token usage with {actual_tokens} tokens from OpenAI response")
        except Exception:
            logger.exception("Failed to update token usage after OpenAI response")
        
        try:
            if hasattr(config, 'RATE_LIMITER') and rate_limiter.RATE_LIMITER:
                rate_limiter.RATE_LIMITER.add_request(actual_tokens)
                logger.debug(f"Added request of {actual_tokens} tokens to rate limiter")
        except Exception:
            logger.exception("Failed to add request to rate limiter after OpenAI response")
        
        # Begin function/tool call handling loop (up to max iterations)
        last_response = response
        max_iterations = 15
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            logger.debug(f"Function call handling iteration {iteration}")
            
            # Try to extract output items from last_response
            try:
                output = getattr(last_response, 'output', None)
                if output is None:
                    try:
                        output = last_response.get('output')  # type: ignore
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
                        if hasattr(item, 'type'):
                            item_type = getattr(item, 'type', None)
                        elif isinstance(item, dict):
                            item_type = item.get('type')
                        
                        # Normalize to string if possible
                        if item_type:
                            item_type_str = str(item_type).lower()
                        else:
                            item_type_str = None
                        
                        if item_type_str in ('function_call', 'tool_call'):
                            logger.debug(f"Detected function/tool call item with type '{item_type_str}'")
                            
                            # Extract call id
                            call_id = None
                            if hasattr(item, 'call_id'):
                                call_id = getattr(item, 'call_id', None)
                            elif hasattr(item, 'id'):
                                call_id = getattr(item, 'id', None)
                            elif isinstance(item, dict):
                                call_id = item.get('call_id') or item.get('id')
                            
                            # Extract function/tool name
                            name = None
                            if hasattr(item, 'name'):
                                name = getattr(item, 'name', None)
                            elif isinstance(item, dict):
                                name = item.get('name')
                            
                            # Sometimes the tool name might be under 'tool' or 'tool_name'
                            if not name and isinstance(item, dict):
                                name = item.get('tool') or item.get('tool_name')
                            if not name and hasattr(item, 'tool'):
                                name = getattr(item, 'tool', None)
                            
                            # Extract arguments; can be dict, object, or JSON string
                            arguments = None
                            if hasattr(item, 'arguments'):
                                try:
                                    arguments = getattr(item, 'arguments', None)
                                except Exception:
                                    arguments = None
                            elif isinstance(item, dict):
                                arguments = item.get('arguments') or item.get('content') or item.get('args')
                            
                            # If arguments is a string, attempt to parse JSON
                            if isinstance(arguments, str):
                                try:
                                    parsed_args = json.loads(arguments)
                                    arguments = parsed_args
                                except Exception:
                                    # keep as string if not JSON
                                    pass
                            
                            # Build normalized function call item
                            function_call_items.append({
                                "call_id": call_id,
                                "name": name,
                                "arguments": arguments,
                                "raw_item": item
                            })
                    except Exception:
                        logger.exception("Error while scanning output items for function calls")
            
            # If no function calls detected, break the loop
            if not function_call_items:
                logger.debug("No function/tool call items detected in response output; exiting function call loop")
                break
            
            # Execute each detected function call
            function_call_outputs = []
            for fc in function_call_items:
                call_id = fc.get('call_id')
                name = fc.get('name')
                arguments = fc.get('arguments')
                
                logger.debug(f"Preparing to execute tool/function '{name}' with call_id '{call_id}' and arguments: {arguments}")
                
                tool_call = {
                    "function": {
                        "name": name,
                        "arguments": arguments
                    },
                    "id": call_id
                }
                
                try:
                    result, error = execute_tool_call(tool_call)
                    if error:
                        logger.error(f"Error executing tool/function '{name}' (call_id: {call_id}): {error}")
                        result_or_error = {"error": str(error)}
                    else:
                        logger.debug(f"Executed tool/function '{name}' (call_id: {call_id}) successfully")
                        result_or_error = result if result is not None else {}
                except Exception as e:
                    logger.exception(f"Exception executing tool/function '{name}' (call_id: {call_id})")
                    result_or_error = {"error": str(e)}
                
                try:
                    output_payload = json.dumps(result_or_error)
                except Exception:
                    try:
                        output_payload = json.dumps({"error": "Unable to serialize tool result"})
                    except Exception:
                        output_payload = "{\"error\": \"serialization_failed\"}"
                
                function_call_outputs.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output_payload
                })
            
            # If we have outputs from executing tools, send them back as a follow-up response
            if function_call_outputs:
                try:
                    followup_params = {'model': strip_openai_prefix(config.MODEL)}
                    # Ensure previous_response_id is the last persisted response id
                    if hasattr(config, 'RESPONSE_ID') and getattr(config, 'RESPONSE_ID'):
                        followup_params['previous_response_id'] = getattr(config, 'RESPONSE_ID')
                    followup_params['input'] = function_call_outputs
                    
                    # Preserve optional params
                    if getattr(config, 'TEMPERATURE', None) is not None:
                        followup_params['temperature'] = getattr(config, 'TEMPERATURE')
                    if getattr(config, 'TOP_P', None) is not None:
                        followup_params['top_p'] = getattr(config, 'TOP_P')
                    if getattr(config, 'FREQUENCY_PENALTY', None) is not None:
                        followup_params['frequency_penalty'] = getattr(config, 'FREQUENCY_PENALTY')
                    if getattr(config, 'PRESENCE_PENALTY', None) is not None:
                        followup_params['presence_penalty'] = getattr(config, 'PRESENCE_PENALTY')
                    if max_output_tokens is not None:
                        followup_params['max_output_tokens'] = max_output_tokens
                    
                    # Add tools if available
                    if tools:
                        followup_params['tools'] = tools
                        followup_params['tool_choice'] = tool_choice
                    
                    logger.debug(f"Sending follow-up responses.create with {len(function_call_outputs)} function_call_output items")
                    followup_response = client.responses.create(**followup_params)
                    
                    logger.debug("Received follow-up response from OpenAI Responses API")
                    
                    # Persist follow-up response id
                    try:
                        follow_id = getattr(followup_response, 'id', None)
                        if follow_id:
                            setattr(config, 'RESPONSE_ID', follow_id)
                            logger.debug(f"Persisted follow-up response id {follow_id} into config.RESPONSE_ID")
                    except Exception:
                        logger.debug("Failed to persist follow-up response id to config, continuing")
                    
                    # Extract token usage for follow-up response
                    follow_tokens = None
                    try:
                        usage = getattr(followup_response, 'usage', None)
                        if usage is None:
                            follow_tokens = None
                        else:
                            if isinstance(usage, dict):
                                follow_tokens = usage.get('total_tokens') or usage.get('total_token_count') or usage.get('total')
                            else:
                                follow_tokens = getattr(usage, 'total_tokens', None) or getattr(usage, 'total_token_count', None) or getattr(usage, 'total', None)
                    except Exception:
                        follow_tokens = None
                    
                    if follow_tokens is None:
                        follow_tokens = 0
                    
                    # Update token usage and rate limiter for follow-up
                    try:
                        update_token_usage(follow_tokens)
                        logger.debug(f"Updated token usage with {follow_tokens} tokens from follow-up OpenAI response")
                    except Exception:
                        logger.exception("Failed to update token usage after follow-up OpenAI response")
                    
                    try:
                        if hasattr(config, 'RATE_LIMITER') and rate_limiter.RATE_LIMITER:
                            rate_limiter.RATE_LIMITER.add_request(follow_tokens)
                            logger.debug(f"Added follow-up request of {follow_tokens} tokens to rate limiter")
                    except Exception:
                        logger.exception("Failed to add follow-up request to rate limiter after OpenAI response")
                    
                    # Set last_response to followup_response and continue loop
                    last_response = followup_response
                except Exception as e:
                    logger.exception("Failed to send follow-up responses.create for function call outputs")
                    # If follow-up fails, break to avoid infinite loop
                    break
            else:
                # No outputs to send back; break loop
                break
        
        # After loop finishes, normalize the last_response into wrapper as before
        output_text = ""
        try:
            # Prefer output_text if present
            if hasattr(last_response, 'output_text') and last_response.output_text:
                output_text = last_response.output_text
            else:
                # Attempt to extract from response.output which may be a list of items
                output = getattr(last_response, 'output', None)
                if output is None:
                    # Some SDKs might store textual output under 'choices' or other shapes
                    # Try to read last_response.get('output') if possible
                    try:
                        output = last_response.get('output')  # type: ignore
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
                            if 'content' in item:
                                content = item['content']
                                if isinstance(content, list):
                                    # list of dicts or strings
                                    for sub in content:
                                        if isinstance(sub, str):
                                            parts.append(sub)
                                        elif isinstance(sub, dict):
                                            # nested content may have 'text' or 'content'
                                            parts.append(sub.get('text') or sub.get('content') or "")
                                elif isinstance(content, str):
                                    parts.append(content)
                            elif 'text' in item:
                                parts.append(item.get('text') or "")
                            elif 'message' in item and isinstance(item.get('message'), dict):
                                msg = item.get('message')
                                # message may contain 'content' as string or list
                                if isinstance(msg.get('content'), str):
                                    parts.append(msg.get('content'))
                                elif isinstance(msg.get('content'), list):
                                    for sub in msg.get('content'):
                                        if isinstance(sub, str):
                                            parts.append(sub)
                                        elif isinstance(sub, dict):
                                            parts.append(sub.get('text') or sub.get('content') or "")
                        else:
                            # Fallback string conversion
                            try:
                                parts.append(str(item))
                            except Exception:
                                pass
                    output_text = "".join(parts)
                elif isinstance(output, dict):
                    # Try common keys
                    if 'content' in output:
                        c = output['content']
                        if isinstance(c, str):
                            output_text = c
                        elif isinstance(c, list):
                            output_text = "".join(x if isinstance(x, str) else x.get('text', '') for x in c)
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
            "id": getattr(last_response, 'id', None),
            "choices": [{"message": {"content": output_text}}],
            "usage": {"total_tokens": actual_tokens}
        }
        
        logger.debug("Normalized OpenAI response into internal wrapper format")
        return wrapper
        
    except Exception as e:
        logger.error(f"Responses API call failed: {e}", exc_info=True)
        raise


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
        if not hasattr(response, 'choices') or not response.choices:
            raise ValueError("Invalid response format: missing choices")
        
        if len(response.choices) == 0:
            raise ValueError("Invalid response format: empty choices")
        
        first_choice = response.choices[0]
        if not hasattr(first_choice, 'message'):
            raise ValueError("Invalid response format: missing message in choice")
        
        logger.debug("Successfully converted response format")
        return response
        
    except Exception as e:
        logger.error(f"Error converting response format: {e}", exc_info=True)
        raise


def handle_response_errors(error, user_input=None):
    """Handle responses API specific errors with appropriate logging.
    
    Args:
        error (Exception): The error that occurred
        user_input (str, optional): The original user input for context
        
    Returns:
        tuple: (None, error_message) following llm.py error format
    """
    error_context = f" for input: {user_input[:100]}..." if user_input and len(user_input) > 100 else f" for input: {user_input}" if user_input else ""
    
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
    else:
        error_msg = f"Responses API error{error_context}: {str(error)}"
        logger.error(f"General responses API error: {error}", exc_info=True)
    
    return None, error_msg


def response_completion(user_input, log_prefix='', error_message='Error during responses API completion'):
    """Main entry point for responses API completion.
    
    This function handles the complete flow for responses API:
    1. Validates configuration
    2. Prepares messages
    3. Estimates tokens
    4. Validates messages
    5. Calls responses API
    6. Processes response
    7. Updates token usage
    
    Args:
        user_input (str): The user's input/query
        log_prefix (str): Prefix for log messages
        error_message (str): Default error message
        
    Returns:
        tuple: (response, error_message) where response is None on error
    """
    try:
        logger.debug(f"{log_prefix} Starting responses API completion")
        
        # Validate configuration
        validate_responses_config()
        
        # Prepare messages for responses API
        messages = prepare_response_messages(user_input)
        
        # Estimate token count
        estimated_tokens = estimate_response_tokens(messages)
        
        # Validate message order
        try:
            validate_tool_message_order(messages)
        except ValueError as ve:
            logger.error(f"Message validation failed for responses API: {ve}")
            return None, str(ve)
        
        # Check if we're within token limits
        if hasattr(config, 'MODEL_MAX_TPM') and estimated_tokens > config.MODEL_MAX_TPM:
            error_msg = (
                f"Input too large: {estimated_tokens} tokens "
                f"vs model limit {config.MODEL_MAX_TPM}. Cannot send request to responses API. "
                "Please reduce the size of your input."
            )
            logger.error(error_msg)
            return None, error_msg
        
        # Apply rate limiting if configured
        if hasattr(config, 'RATE_LIMITER') and rate_limiter.RATE_LIMITER:
            wait_result = rate_limiter.RATE_LIMITER.wait_if_needed(estimated_tokens)
            if wait_result is None:
                error_msg = (
                    f"Rate limit safety threshold exceeded: {estimated_tokens} tokens. "
                    f"Model limit {getattr(config, 'MODEL_MAX_TPM', 'unknown')} tokens. "
                    "Reduce the size of your request."
                )
                logger.error(error_msg)
                return None, error_msg
        
        # Call responses API
        api_response = call_responses_api(messages)
        
        # Convert response format
        response = convert_response_format(api_response)
        
        logger.debug(f"{log_prefix} Successfully completed responses API request")
        return response, None
        
    except Exception as e:
        return handle_response_errors(e, user_input)


def get_response_initial_completion(user_input):
    """Get initial response from responses API for the query.
    
    Args:
        user_input (str): The user's input/query
        
    Returns:
        tuple: (response, error_message) where response is None on error
    """
    logger.debug("Getting initial responses API response...")
    return response_completion(
        user_input,
        log_prefix="Initial responses API request:",
        error_message="I apologize, but I encountered an error processing your request via responses API. Please try again"
    )
