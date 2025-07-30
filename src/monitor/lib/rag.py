
import logging
import os
import ollama
import json

from monitor import config 

logger = logging.getLogger(__name__)

from monitor.lib.external_services import send_query_to_indexing_service
from monitor.lib.rate_limiter import RATE_LIMITER
from monitor.lib.ecs import embed_directory
from monitor.lib.display_output import highlightMarkdown
from monitor.lib.colors import red, yellow, blue, reset 

from monitor.lib.token_management import count_message_tokens, update_token_usage

# Additional imports for print_raw_code
try:
    from pygments.lexers import SwiftLexer
    from pygments.formatters import TerminalFormatter
except ImportError as e:
    logger.error("Failed to import SwiftLexer or TerminalFormatter: %s", str(e))
    raise ImportError(
        "Required pygments components (SwiftLexer and TerminalFormatter) are not available. "
        "Please install pygments and ensure necessary lexers/formatters are accessible."
    )

OLLAMA_CONVERSATION_HISTORY = []

def print_raw_code(results):
    """Print the raw_code_full from query results."""
    logger.debug("print_raw_code called with results count: %d", len(results))
    for entry in results:
        raw_code = entry.get('raw_code_full', None)
        if not isinstance(raw_code, str) or not raw_code:
            logger.warning("Skipped entry without valid 'raw_code_full' (missing or malformed): %s", entry)
            continue
        try:
            highlighted_output = highlight(raw_code, SwiftLexer(), TerminalFormatter(reset=True))
            print(f"{highlighted_output}\n{'!!!'*50}")
        except Exception as e:
            logger.error("Error highlighting code snippet: %s", str(e), exc_info=True)

def _detect_query_type(query, user_input):
    """
    Detect the type of query based on the query topic and user input.
    
    Args:
        query (str): The search query topic
        user_input (str): The user's question or request
        
    Returns:
        str: The query type ('explanation', 'implementation', 'debugging', or 'general')
    """
    combined_text = f"{query} {user_input}".lower()
    
    # Check for explanation queries
    if any(kw in combined_text for kw in [
        "how", "explain", "describe", "what is", "what are", "tell me about", 
        "overview", "understand", "architecture", "design", "pattern", "concept"
    ]):
        return "explanation"
    
    # Check for implementation queries
    elif any(kw in combined_text for kw in [
        "implement", "create", "add", "build", "develop", "write", "code", 
        "function", "method", "class", "feature", "new"
    ]):
        return "implementation"
    
    # Check for debugging queries
    elif any(kw in combined_text for kw in [
        "fix", "error", "bug", "issue", "problem", "crash", "exception", 
        "debug", "troubleshoot", "failing", "doesn't work", "doesn't compile"
    ]):
        return "debugging"
    
    # Default to general
    return "general"


def send_directory_to_indexing_service(directory_path):
    """
    Send a directory to the indexing service for embedding.
    
    Args:
        directory_path (str): Path to the directory to embed
    """
    logger.info("Sending directory to indexing service: %s", directory_path)
    if directory_path == ".":
        embed_directory(os.getcwd())
        return
    embed_directory(directory_path)

def build_rag_prompt(query, user_input, max_tokens=None):
    """
    Build a retrieval-augmented prompt for the LLM.
    Extract relevant chunked data from query server results and build a context-rich prompt.
    Adapts the prompt format based on the type of query detected.
    
    Args:
        query (str): The search query for the retrieval system
        user_input (str): The user's input/question
        max_tokens (int, optional): Maximum tokens for context. Defaults to 70% of MODEL_CONTEXT_WINDOW.
    
    Returns:
        str: The formatted prompt with retrieved context
    """
    logger.debug("Building RAG prompt for query: %s", query)
    
    # Set default max_tokens if not provided
    if max_tokens is None:
        # Use 70% of context window for retrieved content, leaving room for the rest of the prompt
        max_tokens = int(config.MODEL_CONTEXT_WINDOW * 0.7)
    
    # Determine query type
    query_type = _detect_query_type(query, user_input)
    logger.debug("Detected query type: %s", query_type)
    
    # Retrieve metadata from the Code Lens service
    response = send_query_to_indexing_service(query)
    results = response.get("results", []) if response else []
    
    # Reserve tokens for system message, user query, and instructions
    # Use count_message_tokens for token counting
    reserved_tokens_str = f"{user_input}"
    reserved_tokens = count_message_tokens({"role": "user", "content": reserved_tokens_str}) + 500  # 500 is a buffer for system and instructions
    available_tokens = max_tokens - reserved_tokens
    
    logger.debug("Token budget for context: %d (max: %d, reserved: %d)", 
                 available_tokens, max_tokens, reserved_tokens)
    
    # Build context with token awareness
    context_parts = []
    used_tokens = 0
    
    for entry in results:
        # Format the entry
        entry_text = (
            f"File: {entry['filename']}\n"
            f"Id: {entry['id']}\n"
            f"Chunk Type: {entry.get('chunk_type', 'None')}\n"
            f"Code Snippet: {entry.get('raw_code_full', 'None')}\n"
            f"Symbol Name: {entry.get('symbol_name', 'None')}\n"
            f"Summaries:\n" + "\n".join(
                f"{s.get('summary_type', 'None').capitalize()}: {s.get('summary', 'None')}"
                for s in entry['summaries']
            )
        )
        
        # Estimate tokens for this entry using count_message_tokens
        message_format = {"role": "user", "content": entry_text}
        entry_tokens = count_message_tokens(message_format)
        
        # If this is the first entry and it's too large, truncate it
        if not context_parts and entry_tokens > available_tokens:
            logger.warning("First result exceeds token budget. Truncating.")
            # Simple truncation - a more sophisticated approach could prioritize certain fields
            truncation_ratio = available_tokens / entry_tokens
            truncated_length = int(len(entry_text) * truncation_ratio * 0.9)  # 10% safety margin
            entry_text = entry_text[:truncated_length] + "\n[Content truncated due to token limits]"
            message_format = {"role": "user", "content": entry_text}
            entry_tokens = count_message_tokens(message_format)
        
        # Check if adding this entry would exceed our token budget
        if used_tokens + entry_tokens > available_tokens:
            logger.debug("Token budget reached after %d entries. Stopping.", len(context_parts))
            break
        
        # Add the entry to our context
        context_parts.append(entry_text)
        used_tokens += entry_tokens
        logger.debug("Added entry %d: %d tokens (total: %d/%d)", 
                     len(context_parts), entry_tokens, used_tokens, available_tokens)
    
    context_section = "\n\n".join(context_parts)
    logger.debug("Context built with %d entries using %d tokens", len(context_parts), used_tokens)
    
    if not context_parts:
        logger.warning("No context could be included within token limits")
        context_section = "[No relevant code context found within token limits]"
    
    # Select appropriate system message and instructions based on query type
    if query_type == "explanation":
        system_message = (
            "You are an expert iOS and Python developer explaining code architecture and functionality. "
            "Focus on providing clear, conceptual explanations that help the user understand the code structure, "
            "patterns, and relationships between components. Use analogies when helpful."
        )
        instructions = """
        - Focus on high-level understanding and code architecture
        - Explain design patterns and key relationships between components
        - Clarify the purpose and responsibilities of different code elements
        - Use simple language and avoid unnecessary technical jargon
        - Provide context on how the code fits into the larger system
        """
    
    elif query_type == "implementation":
        system_message = (
            "You are an expert iOS and Python developer helping implement new code or features. "
            "Focus on providing practical, working code examples that follow the conventions and "
            "patterns established in the existing codebase. Your solutions should be clean, "
            "well-structured, and easy to integrate."
        )
        instructions = """
        - Provide complete, working code solutions that match the existing style
        - Include clear comments explaining your implementation decisions
        - Consider error handling, edge cases, and performance
        - Reference similar patterns from the existing codebase
        - Ensure your solution integrates well with existing code
        """
    
    elif query_type == "debugging":
        system_message = (
            "You are an expert iOS and Python developer helping debug issues in code. "
            "Focus on identifying potential problems, explaining their causes, and suggesting "
            "specific fixes. Be methodical in your analysis and provide clear reasoning for "
            "your suggestions."
        )
        instructions = """
        - Analyze the code for common error patterns and issues
        - Suggest specific fixes with clear explanations
        - Consider potential side effects of your proposed solutions
        - Look for similar patterns in the working parts of the codebase
        - Recommend debugging techniques or tests that might help isolate the issue
        """
    
    else:  # general
        system_message = (
            "You are an expert iOS and Python developer assisting with a large Swift/Objective-C "
            "codebase and Python code. Use the provided context to generate accurate and relevant responses. "
            "If the context is missing key details, do your best with general knowledge but avoid hallucinating code."
        )
        instructions = """
        - Use the provided context when answering
        - If context is insufficient, explain the missing details instead of making assumptions
        - Follow the coding style and conventions in the codebase
        - Provide clear, modular code examples where applicable
        """

    prompt = f"""
    {system_message}

    {context_section}

    ## User Query ##
    {user_input}

    ## Instructions ##
    {instructions}

    Your response:
    """
    logger.debug("RAG prompt built with query type '%s' (context sections: %d)", 
                 query_type, len(context_parts))
    return prompt


def query_using_rag(raw_user_input):
    """
    Process a RAG query using the format 'topic:prompt' and generate a response.
    
    Args:
        raw_user_input (str): The raw input in the format 'topic:prompt'
    """
    logger.info("query_using_rag called (input length: %d)", len(raw_user_input))
    parts = raw_user_input.split(":", 1)
    if len(parts) == 1:
        print(f"{red}Query format: <topic>:<prompt>{reset}")
        logger.warning("Invalid user input format for RAG query: %s", raw_user_input)
        return

    try:
        # Get available tokens from rate limiter - use 80% to leave room for the response
        current_usage = RATE_LIMITER.get_current_usage()
        available_tokens = max(1000, int((RATE_LIMITER.limit - current_usage) * 0.8))
        
        # Cap at model context window
        available_tokens = min(available_tokens, config.MODEL_CONTEXT_WINDOW)
        
        logger.debug("Available tokens for RAG query: %d (rate limit: %d, current usage: %d)",
                    available_tokens, RATE_LIMITER.limit, current_usage)

        # Build RAG prompt with token awareness
        logger.debug("Building RAG prompt with token budget: %d", available_tokens)
        query_topic = parts[0]
        user_query = parts[-1]
        user_input_str = build_rag_prompt(query_topic, user_query, max_tokens=available_tokens)
        
        # Estimate tokens for the full prompt using count_message_tokens
        estimated_tokens = count_message_tokens({"role": "user", "content": user_input_str})
        logger.debug("Estimated tokens for RAG query: %d", estimated_tokens)
        
        # Check if we need to wait due to rate limiting
        RATE_LIMITER.wait_if_needed(estimated_tokens)
        
        # Add to conversation history
        logger.debug("Appending user input to conversation history (length before: %d)", 
                    len(OLLAMA_CONVERSATION_HISTORY))
        OLLAMA_CONVERSATION_HISTORY.append({"role": "user", "content": user_input_str})

        # Send query to Ollama
        ollama_client = ollama.Client(host=config.OLLAMA_CONFIG['host'])
        logger.info("Initiating Ollama chat query (conversation history length: %d)", 
                   len(OLLAMA_CONVERSATION_HISTORY))
        
        response = ollama_client.chat(
            model=config.OLLAMA_CONFIG['model'],
            messages=OLLAMA_CONVERSATION_HISTORY,
            stream=False
        )

        # Process and display response
        query_result = response.message.content
        try:
            highlightMarkdown(query_result)
        except Exception as e:
            logger.error("Failed to display highlighted Ollama response: %s", str(e), exc_info=True)
 
        update_token_usage(estimated_tokens)
        OLLAMA_CONVERSATION_HISTORY.append({"role": "assistant", "content": query_result})

        logger.info("Successfully generated response using Ollama (resp. length: %d)", 
                   len(query_result) if query_result else 0)
        
    except Exception as e:
        logger.error("Unexpected error in Ollama query: %s", str(e), exc_info=True)
