import logging
import litellm

from monitor import config
from monitor.core.tools import TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS
from monitor.lib.message_utils import normalize_message, sanitize_messages
from monitor.lib.token_management import count_message_tokens, update_token_usage
from monitor.lib import rate_limiter
from monitor.lib.llm_utils import dict_to_attr, validate_tool_message_order
from monitor.lib.tool_loading import function_descriptions

logger = logging.getLogger(__name__)


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
            tools = function_descriptions()
            logger.debug(f"Using function descriptions ({len(tools) if tools else 0} tools)")
        
        # Set tool choice strategy
        tool_choice = "auto" if tools else None
        
        return tools, tool_choice
        
    except Exception as e:
        logger.error(f"Error getting tools for model: {e}", exc_info=True)
        return None, None


def call_responses_api(messages):
    """Make the actual call to the responses API via litellm.
    
    Args:
        messages (list): Prepared messages for the API
        
    Returns:
        dict: Raw response from the API
        
    Raises:
        Exception: Any API-related errors
    """
    try:
        logger.debug("Calling responses API via litellm")
        
        # Get tools for the current model
        tools, tool_choice = get_tools_for_model()
        
        # Build completion parameters
        completion_params = {
            'model': config.MODEL,
            'messages': messages,
            'temperature': getattr(config, 'TEMPERATURE', 0.7),
            'max_tokens': getattr(config, 'MAX_COMPLETION_TOKENS', None),
            'top_p': getattr(config, 'TOP_P', None),
            'frequency_penalty': getattr(config, 'FREQUENCY_PENALTY', None),
            'presence_penalty': getattr(config, 'PRESENCE_PENALTY', None),
        }
        
        # Add tools if available
        if tools:
            completion_params['tools'] = tools
            completion_params['tool_choice'] = tool_choice
            logger.debug(f"Added {len(tools)} tools to responses API call with choice '{tool_choice}'")
        else:
            logger.debug("No tools available for responses API call")
        
        # Use litellm.completion for responses API
        response = litellm.completion(**completion_params)
        
        logger.debug("Successfully received response from responses API")
        return response
        
    except Exception as e:
        logger.error(f"Responses API call failed: {e}", exc_info=True)
        raise


def convert_response_format(api_response):
    """Convert responses API response to expected format.
    
    Ensures the response format matches what the rest of the system expects.
    
    Args:
        api_response (dict): Raw API response
        
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
        
        # Update token usage
        actual_tokens = (
            response.usage.total_tokens
            if hasattr(response, 'usage') and hasattr(response.usage, 'total_tokens')
            else estimated_tokens
        )
        update_token_usage(actual_tokens)
        
        # Update rate limiter
        if hasattr(config, 'RATE_LIMITER') and rate_limiter.RATE_LIMITER:
            rate_limiter.RATE_LIMITER.add_request(actual_tokens)
        
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