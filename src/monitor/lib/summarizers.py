
import litellm
import logging

logger = logging.getLogger(__name__)

def summarize_conversation_for_platform(platform: str, model, conversation_history, system_prompt="You are an expert text summarizer assistant."):
    """Summarize conversation history for a given platform formatting."""
    history_length = len(conversation_history) if conversation_history else 0
    if history_length < 10:
        logger.warning(f"History length too short (<10) to summarize.")
        return None

    logger.debug("Summarizing history with platform: %s and %d messages in history",
                platform, history_length)
    messages = [msg for msg in conversation_history if msg.get('content')]
    logger.debug("Filtered to %d non-empty messages", len(messages))
    
    if platform == "twitch":
        instructions = f"""
        Summarize the following conversation concisely, do not mention file names or directory names, but capturing the main points and context: {str(messages)}.
        Replace the word 'A User' with 'I'.
        Replace the word 'assistant' with 'AI'.
        Start the summary with the word: 'Summary:'.
        Limit the summary to at most 450 characters.
        The summary is meant to be posted to a Twitch channel and should be geared towards casual software developers.
"""
    elif platform == "twitter":
        instructions = f"""
        Summarize the following conversation concisely, do not mention file names or directory names, but capturing the main points and context: {str(messages)}.
        Replace the word 'A User' with 'I'.
        Replace the word 'assistant' with 'AI'.
        Start the summary with the word: 'Summary:'.
        Limit the summary to at most 280 characters.
        The summary is meant to be posted to a Twitter and should be geared towards casual software developers.
"""
    elif platform == "linkedin":
        instructions = f"""
        Summarize the following conversation concisely, do not mention file names or directory names, but capturing the main points and context: {str(messages)}. Replace the word 'A User' with 'I'. Replace the word 'assistant' with 'AI'. Start the summary with the sentence: 'What I've been working on lately:'. Limit the summary to at most 512 characters and the summary should have one paragraph with bullet points. End the summary with the sentence: '-- Rodney'. The summary should be written in a self-promotional style since, the summary is meant to be posted to LinkedIn and should be geared towards potential employers and collaborators.
"""
    else:
        logger.error("Unknown platform: %s", platform)
        return ""

    try:
        logger.debug("Calling litellm completion with model: %s for platform: %s", model, platform)
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": f"{system_prompt}"},
                {"role": "user", "content": instructions}
            ]
        )
        logger.debug("Successfully received response from litellm for platform: %s", platform)
    except Exception as e:
        logger.error("Error during litellm completion for platform %s: %s", platform, str(e), exc_info=True)
        return ""

    summary = response.choices[0].message
    logger.info("Generated summary for %s with %d characters", 
               platform.capitalize(), len(summary['content']) if summary.get('content') else 0)  
    # print(f">>>> {summary}")
    return summary['content']

def summarize_conversation_for_twitch(conversation_history, model):
    """Summarize conversation history for Twitch formatting."""
    return summarize_conversation_for_platform("twitch", model, conversation_history)

def summarize_conversation_for_twitter(conversation_history, model):
    """Summarize conversation history for Twitter formatting."""
    return summarize_conversation_for_platform("twitter", model, conversation_history)

def summarize_conversation_for_linkedin(conversation_history, model):
    """Summarize conversation history for LinkedIn formatting."""
    return summarize_conversation_for_platform("linkedin", model, conversation_history)


