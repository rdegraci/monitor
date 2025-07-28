"""
Message utilities for handling conversation history and message formatting.
This module provides utilities for formatting messages for different LLM providers,
including special handling for Anthropic's ephemeral caching mechanism.
"""

import logging
import re

logger = logging.getLogger(__name__) 

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

def prepare_messages_with_cache_control(messages, model_name, disable_for_tool_calls=False):
    """
    Prepare messages with cache_control for Anthropic models to enable efficient caching.
    
    Args:
        messages (list): List of message dictionaries
        model_name (str): The name of the model being used
        disable_for_tool_calls (bool): If True, disables caching when tool calls are expected
        
    Returns:
        list: Properly formatted messages with cache_control parameters if applicable
    """
    logger.debug("Entering prepare_messages_with_cache_control with model_name=%s, disable_for_tool_calls=%s, message_count=%s", 
                model_name, disable_for_tool_calls, len(messages))
    
    if not is_anthropic_model(model_name):
        logger.debug("Skipping cache control - %s is not an Anthropic model", model_name)
        return messages
    
    logger.info("Preparing messages with cache control for Anthropic model %s", model_name)
        
    # Check if we're expecting tool calls and should disable caching
    should_disable = False
    if disable_for_tool_calls:
        try:
            should_disable = any(
                msg.get('content', '').lower().find('tool') != -1 or 
                msg.get('content', '').lower().find('function') != -1
                for msg in messages[-3:] # Check recent messages
            )
            
            if should_disable:
                logger.debug("Tool/function calls detected in recent messages, disabling cache control")
                return messages
        except Exception as e:
            logger.error("Error checking for tool calls: %s", str(e), exc_info=True)
            # Continue with default behavior if there's an error

    # Deep copy the messages to avoid modifying the original
    prepared_messages = messages.copy()
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


