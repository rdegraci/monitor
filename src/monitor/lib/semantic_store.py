
import litellm
import json
import os
import logging
import traceback

from monitor.lib.redis_utils import (
    save_to_memory,
    update_memory
)

logger = logging.getLogger(__name__)

class SemanticStore:
    """
    An autonomous semantic memory store that connects to OpenAI (GPT-4o) via LiteLLM,
    reasons about what should be stored, and uses external Redis tools to write memory.
    """
    def __init__(self, tools, openai_api_key, system_prompt=None):
        """
        Args:
            tools (dict): Dict containing at least 'save_to_memory' fn matching app.py signature.
            openai_api_key (str): OpenAI key for GPT-4o access.
            system_prompt (str): Optional initial system message for LLM reasoning policies.
        """
        self.tools = tools
        self.openai_api_key = openai_api_key
        self.system_prompt = system_prompt or (
            "You are a memory agent. Analyze each message and decide if info should be stored."
            "Store facts, preferences, or instructions in Redis using the provided memory tool."
            "Respond ONLY with a JSON object: {\"to_remember\": ..., \"key\": ...} or null if none."
        )
        self.litellm = litellm

    def process(self, user_prompt):
        """
        Sends a prompt to the LLM, lets it decide what (if anything) should be remembered,
        and calls the Redis memory tool accordingly.
        """
        logger.debug("[SemanticStore] Incoming user_prompt: %s", user_prompt)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        try:
            completion = self.litellm.completion(
                model="openai/gpt-4o",
                messages=messages,
                api_key=self.openai_api_key
            )
            logger.debug("[SemanticStore] Raw LLM completion result: %r", completion)
        except Exception as e:
            logger.error("[SemanticStore] LLM completion call failed: %s\n%s", e, traceback.format_exc())
            return None
        try:
            result = json.loads(completion['choices'][0]['message']['content'])
            logger.debug("[SemanticStore] Parsed JSON result from LLM: %r", result)
        except Exception as e:
            logger.error("[SemanticStore] Error parsing LLM response: %s\n%s", e, traceback.format_exc())
            logger.debug("[SemanticStore] Exiting early due to failed JSON parse.")
            return None

        if result and isinstance(result, dict) and "to_remember" in result and "key" in result:
            try:
                logger.debug(
                    "[SemanticStore] Entering save_to_memory with key: %r, value: %r",
                    result['key'], result['to_remember']
                )
                outcome = self.tools['save_to_memory'](
                    key=result['key'],
                    value=result['to_remember']
                )
                logger.info("[SemanticStore] Stored memory under key: %s", result['key'])
                return outcome
            except Exception as e:
                logger.error("[SemanticStore] Memory storage failed: %s\n%s", e, traceback.format_exc())
                logger.debug("[SemanticStore] Exiting early due to memory storage failure.")
                return None
        else:
            logger.debug("[SemanticStore] Exiting early: Nothing to remember or invalid response. Result: %r", result)
            logger.info("[SemanticStore] Nothing to remember or invalid response.")
            return None

# Set up SemanticStore using the same Redis memory tools as app.py
SEMANTIC_STORE = SemanticStore(
    tools={
        "save_to_memory": save_to_memory,
        "update_memory": update_memory,
    },
    openai_api_key=os.environ.get("OPENAI_API_KEY")  
)

def semantic_store_command(args):
    # args: the text to analyze and possibly remember
    SEMANTIC_STORE.process(args)
    print("Semantic memory processed for input")
