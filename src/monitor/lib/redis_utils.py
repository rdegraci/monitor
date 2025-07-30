
import logging
import json
import redis
import time
import threading
from functools import wraps
from typing import Dict, Optional, Union, Tuple, List

from redis.exceptions import ConnectionError, TimeoutError, RedisError

from monitor import config 

from monitor.lib.colors import red, blue, yellow, reset 
from monitor.lib.token_management import count_message_tokens, update_token_usage

logger = logging.getLogger(__name__)

# Thread-local storage for Redis client
_redis_client = threading.local()

REDIS_HOST=None 
REDIS_PORT=6379 
REDIS_DB=0 
REDIS_MAX_RETRIES=3 
REDIS_RETRY_INTERVAL=1

def configure_redis_utils(host, port, db, max_retries, retry_interval):
    global REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_MAX_RETRIES, REDIS_RETRY_INTERVAL
    REDIS_HOST = host
    REDIS_PORT = port
    REDIS_DB = db
    REDIS_MAX_RETRIES = max_retries
    REDIS_RETRY_INTERVAL = retry_interval

def get_redis_client() -> redis.Redis:
    """
    Get or create a Redis client instance.
    Uses thread-local storage to ensure thread safety.

    Returns:
        redis.Redis: Redis client instance.
    """

    if not config.MEMORY_SERVICES:
        logger.info("Redis server not available. No MEMORY_SERVICES.")
        return None

    logger.debug("Entering get_redis_client")
    if not hasattr(_redis_client, 'instance'):
        try:
            _redis_client.instance = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                decode_responses=True,  # Automatically decode response bytes to str
                socket_timeout=5,  # 5 seconds socket timeout
                socket_connect_timeout=5,  # 5 seconds connection timeout
                retry_on_timeout=True,
                health_check_interval=30  # Check connection health every 30 seconds
            )
            logger.debug("Created new Redis client with host=%s, port=%s, db=%s", REDIS_HOST, REDIS_PORT, REDIS_DB)
        except RedisError as e:
            logger.error("Failed to create Redis client: %s", e)
            raise
    return _redis_client.instance

def with_redis_retry(max_retries=REDIS_MAX_RETRIES, retry_interval=REDIS_RETRY_INTERVAL):
    """
    Decorator that implements retry logic for Redis operations.

    Args:
        max_retries (int): Maximum number of retry attempts.
        retry_interval (int): Time to wait between retries in seconds.

    Returns:
        callable: Decorated function with retry logic.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger.debug("Calling %s with retry logic: args=%s, kwargs=%s", func.__name__, args, kwargs)
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (ConnectionError, TimeoutError, RedisError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:  # Don't sleep on the last attempt
                        logger.warning("Redis operation failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
                        time.sleep(retry_interval)
                        # Reset client connection
                        if hasattr(_redis_client, 'instance'):
                            delattr(_redis_client, 'instance')
            logger.error("Redis operation failed after %d attempts: %s", max_retries, last_exception)
            # Don't propagate further, but return reasonable error structure or None:
            return {"error": f"Redis operation failed after {max_retries} attempts: {last_exception}"}
        return wrapper
    return decorator

@with_redis_retry()
def verify_ttl(key: str) -> Tuple[bool, int]:
    """
    Verify the TTL (time to live) of a key in Redis.

    Args:
        key (str): The Redis key to check.

    Returns:
        Tuple[bool, int]: 
            - Boolean indicating if key exists.
            - Integer TTL in seconds (-2 if key doesn't exist, -1 if no TTL).
    """
    logger.debug("Entering verify_ttl with key=%s", key)
    try:
        client = get_redis_client()
        exists = client.exists(key)
        ttl = client.ttl(key) if exists else -2
        logger.debug("verify_ttl result: exists=%s, ttl=%s", exists, ttl)
        return bool(exists), ttl
    except RedisError as e:
        logger.error("Redis error in verify_ttl for key %s: %s", key, e)
        return False, -2

@with_redis_retry()
def save_to_memory(key: str, value: str, ttl: Optional[int] = 900) -> Union[str, None]:
    """
    Deprecated: Use update_memory instead.

    Args:
        key (str): The Redis key.
        value (str): Value to save.
        ttl (Optional[int]): Time to live for the key in seconds.

    Returns:
        Union[str, None]: Result message or None on failure.
    """
    logger.debug("Entering save_to_memory with key=%s, value=(omitted), ttl=%s", key, ttl)
    logger.warning("save_to_memory is deprecated. Use update_memory instead.")
    return update_memory(user_input=value, response="", key=key)

@with_redis_retry()
def update_memory(user_input: str, response: str = "", key: Optional[str] = None, ttl: Optional[int] = 1800) -> Union[str, None]:
    """
    Save a value in Redis under the specified key.
    Optionally applies a Time-To-Live (TTL) to the key-value pair.

    Args:
        user_input (str): The user's input to be stored.
        response (str, optional): The system's response to be stored.
        key (Optional[str], optional): The Redis key under which the value is stored. If None, a timestamped key is generated.
        ttl (Optional[int], optional): Time in seconds after which the key should expire. Defaults to 30 minutes (1800 seconds).

    Returns:
        Union[str, None]: String message describing the operation result or None on failure.
    """
    logger.debug(
        "Entering update_memory with user_input=%s, response=%s, key=%s, ttl=%s",
        (user_input[:40] + "...") if user_input and len(user_input) > 40 else user_input,
        (response[:40] + "...") if response and len(response) > 40 else response,
        key, ttl
    )
    try:
        client = get_redis_client()
        if key is None:
            prefix = f"conversation:{time.time()}"
        else:
            prefix = f"conversation:{key}"

        logger.debug("Saving to memory: %s with user_input=(omitted), response=(omitted), ttl=%s", prefix, ttl)

        # Store data in a structured format using JSON
        data = {
            "user_input": user_input,
            "response": response,
            "timestamp": time.time()
        }
        try:
            json_data = json.dumps(data)
        except (TypeError, ValueError) as e:
            logger.error("Could not serialize data to JSON for key %s: %s", prefix, e)
            return f"Could not serialize data to JSON: {e}"

        # Use pipeline for atomic operations
        try:
            with client.pipeline() as pipe:
                pipe.set(prefix, json_data)
                if ttl:
                    pipe.expire(prefix, ttl)
                pipe.execute()
        except RedisError as e:
            logger.error("Failed to save data to Redis for key %s: %s", prefix, e)
            return f"Failed to save to Redis: {str(e)}"

        exists, actual_ttl = verify_ttl(prefix)
        if not exists:
            logger.error("Key %s was not saved successfully", prefix)
            return "Key was not saved successfully"
        if ttl and (actual_ttl == -1 or actual_ttl <= 0):
            try:
                client.delete(prefix)
            except RedisError as e:
                logger.error("Failed to cleanup after TTL verification for key %s: %s", prefix, e)
            logger.error("TTL verification failed for key %s. Expected ~%s, got %s", prefix, ttl, actual_ttl)
            return f"TTL verification failed. Expected ~{ttl}, got {actual_ttl}"

        data["ttl"] = actual_ttl
        result_message = f"Successfully saved '{user_input}' under key: {prefix} with TTL: {actual_ttl}s"
        logger.info("Successfully saved user_input under key %s with TTL %s", prefix, actual_ttl)
        logger.info(result_message)
        return result_message

    except RedisError as e:
        error_data = {
            "error": str(e),
            "key": key,
            "timestamp": time.time(),
            "ttl": None
        }
        error_message = f"Failed to save to Redis: {str(e)}"
        logger.error("Failed to save to Redis for key %s: %s", key, e)
        return error_message

@with_redis_retry()
def read_from_memory(key: str) -> Union[str, None, Dict[str, str]]:
    """
    Retrieve a value from Redis based on the specified key.
    If the key starts with 'conversation:', it will be used as is;
    otherwise, returns None.

    Args:
        key (str): The Redis key from which to retrieve the value.

    Returns:
        Union[str, None, Dict[str, str]]: Result message, None if not found, or structured error info if decoding fails.
    """
    logger.debug("Entering read_from_memory with key=%s", key)
    try:
        client = get_redis_client()
        logger.debug("Reading from memory: %s", key)

        if key.startswith('conversation:'):
            search_key = key
        else:
            search_key = f"conversation:{key}"

        exists, ttl = verify_ttl(search_key)
        value = client.get(search_key) if exists else None

        if value is None:
            message = f"No value found in memory for search_key: {search_key}"
            logger.warning("No value found in memory for search_key: %s", search_key)
            logger.warning(message)
            return None

        try:
            if isinstance(value, str):
                parsed_value = json.loads(value)
                result = parsed_value.get('response')
            else:
                result = value
            message = f"Successfully retrieved `{result}` for search_key: {search_key} (TTL: {ttl}s)"
            logger.info("Successfully retrieved key %s (TTL: %s)", search_key, ttl)
            logger.info(message)
            return message
        except (json.JSONDecodeError, TypeError) as e:
            message = f"Retrieved value is not valid JSON for search_key: {search_key}: {e}"
            logger.warning("Retrieved value is not valid JSON for search_key: %s: %s", search_key, e)
            logger.warning(message)
            return {
                "error": "Retrieved value is not valid JSON",
                "key": search_key,
                "raw_value": value,
                "exception": str(e)
            }
    except RedisError as e:
        error_message = f"Failed to read from Redis: {str(e)}"
        logger.error("Failed to read from Redis for key %s: %s", key, e)
        return {"error": error_message, "key": key}

@with_redis_retry()
def fetch_memory_for_context() -> List[str]:
    """
    Fetch all valid (non-expired) keys from Redis that match the pattern 'conversation:*'.
    Keys are sorted by their timestamp in descending order (newest first).

    Returns:
        List[str]: List of conversation keys.
    """
    logger.debug("Entering fetch_memory_for_context")
    keys = []
    try:
        client = get_redis_client()
        # Get all conversation keys
        all_keys = client.keys(pattern="conversation:*")

        # Filter out expired keys and sort by timestamp
        valid_keys = []
        for key in all_keys:
            exists, ttl = verify_ttl(key)
            if exists:
                try:
                    data = client.get(key)
                    if data:
                        try:
                            parsed_data = json.loads(data)
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.warning("Could not parse data for key %s: %s", key, e)
                            continue
                        timestamp = parsed_data.get('timestamp', 0)
                        valid_keys.append((key, timestamp))
                except RedisError as e:
                    logger.warning("Error getting value for key %s: %s", key, e)
                    continue

        # Sort keys by timestamp (newest first)
        valid_keys.sort(key=lambda x: x[1], reverse=True)
        keys = [k[0] for k in valid_keys]

        logger.info("Fetched %d valid conversation keys", len(keys))
        return keys
    except RedisError as e:
        logger.error("Failed to fetch memory keys: %s", e)
        return keys

@with_redis_retry()
def fetch_memory_keys_as_json() -> str:
    """
    Fetch all valid (non-expired) keys from Redis that match the pattern 'conversation:*'
    and return them as a JSON string.

    Returns:
        str: A JSON string representing a list of conversation keys, or a structured error message.
    """
    logger.debug("Entering fetch_memory_keys_as_json")
    try:
        keys = fetch_memory_for_context()
        try:
            json_keys = json.dumps(keys)
            logger.info("Returning %d memory keys as JSON", len(keys))
            return json_keys
        except (TypeError, ValueError) as e:
            logger.error("Error serializing memory keys to JSON: %s", e)
            return json.dumps({"error": "Serialization error", "exception": str(e)})
    except RedisError as e:
        logger.error("Failed to fetch memory keys as JSON: %s", e)
        return json.dumps({"error": "RedisError on fetch_memory_keys_as_json", "exception": str(e)})


def prepend_memory_to_history() -> None:
    """
    Prepend stored Redis conversation memories to the given conversation history list.
    This ensures that historical memory is considered first in interactions.

    Args:
        None, but updates config.CONVERSATION_HISTORY list in place.
    """
    logger.debug(
        "Entering prepend_memory_to_history with config.CONVERSATION_HISTORY(len)=%d", 
        len(config.CONVERSATION_HISTORY) if config.CONVERSATION_HISTORY is not None else 0)
    try:
        if not config.MEMORY_SERVICES:
            logger.warning("Unable to prepend memory to history. No MEMORY_SERVICES.")
            return
        client = get_redis_client()
        logger.debug("Prepending memory to history")
        keys = fetch_memory_for_context()
        memory_entries = []

        for key in keys:
            exists, ttl = verify_ttl(key)
            if exists:
                try:
                    value = client.get(key)
                except RedisError as e:
                    logger.warning("Error retrieving value for key %s: %s", key, e)
                    continue
                if value:
                    try:
                        data = json.loads(value)
                        if isinstance(data, dict) and 'user_input' in data and 'response' in data:
                            entry = f"User: {data['user_input']}\nResponse: {data['response']}"
                            memory_entries.append(entry)
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning("Failed to decode JSON for key %s: %s", key, e)
                        memory_entries.append(str(value))

        if memory_entries:
            memory_dict = {
                "role": "system",
                "content": "Previous conversation context:\n" + "\n\n".join(memory_entries)
            }
            if not config.CONVERSATION_HISTORY:
                config.CONVERSATION_HISTORY.insert(0, memory_dict)
            else:
                config.CONVERSATION_HISTORY[0] = memory_dict
            logger.info("Prepended memory to history with %d memory entries", len(memory_entries))
    except Exception as e:
        logger.error("Error while prepending memory to history: %s", e, exc_info=True)
        # Don't raise the exception as this is a non-critical operation

def prepare_model_input(user_input: str) -> None:
    """
    Prepare input data for the model by appending current user input to the past memory.
    This function ensures the model has access to full conversation context.

    Args:
        user_input (str): The newest user input to include in the history.

    Returns:
        None.
    """
    logger.debug(
        "Entering prepare_model_input with user_input=%s, config.CONVERSATION_HISTORY(len)=%d",
        (user_input[:40] + "...") if user_input and len(user_input) > 40 else user_input,
        len(config.CONVERSATION_HISTORY) if config.CONVERSATION_HISTORY is not None else 0
    )
    prepend_memory_to_history()
    append_to_history_with_count(
        {"role": "user", "content": user_input},
        config.CONVERSATION_HISTORY,
        count_message_tokens,
        update_token_usage
    )
    logger.info("Model input prepared and appended for user_input")

def append_to_history_with_count(message, conversation_history, count_message_tokens_func, update_token_usage_func):
    """
    Adds a message to the conversation history list, updates token usage accounting, and logs information.

    Args:
        message (dict): The message to add.
        conversation_history (list): The conversation history list.
        count_message_tokens_func (callable): Function to count tokens.
        update_token_usage_func (callable): Function to update token usage.

    Returns:
        None.
    """
    conversation_history.append(message)
    num_tokens = count_message_tokens_func([message])
    update_token_usage_func(num_tokens)
    logger.info("Appended message to history and updated token usage by %d tokens.", num_tokens)

@with_redis_retry()
def delete_from_memory(key: str) -> bool:
    """
    Delete a value from Redis based on the specified key.
    If the key starts with 'conversation:', it will be used as is; otherwise, 'conversation:' will be prepended.

    Args:
        key (str): The Redis key to delete (without 'conversation:' prefix, unless explicitly provided).

    Returns:
        bool: True if the key was deleted, False otherwise.
    """
    logger.debug("Entering delete_from_memory with key=%s", key)
    client = get_redis_client()
    if not key.startswith('conversation:'):
        redis_key = f"conversation:{key}"
    else:
        redis_key = key
    try:
        deleted = client.delete(redis_key)
        if deleted:
            logger.info("Successfully deleted %s from memory.", redis_key)
            return True
        else:
            logger.warning("No key %s found to delete.", redis_key)
            return False
    except RedisError as e:
        logger.error("Error deleting key %s: %s", redis_key, e)
        return False

def dump_memories(arg):
    """
    Built-in command :memories to print all long-term and short-term memories stored in Redis.

    Args:
        arg: Not used; for CLI/UX compatibility and future extensibility.

    Returns:
        None
    """
    logger.debug("Entering dump_memories")
    print("\n--- Redis Memories Dump ---\n")
    keys = fetch_memory_for_context()
    if not keys:
        print("[info] No conversation/long-term memories stored in Redis.")
        logger.info("No conversation/long-term memories stored in Redis.")
        return
    client = get_redis_client()
    for key in keys:
        print(f"Key: {key}")
        try:
            value = client.get(key)
            if value:
                try:
                    parsed = json.loads(value)
                    for k, v in parsed.items():
                        print(f"  {k}: {v}")
                except Exception:
                    print(f"  Raw: {value}")
            else:
                print("  [empty entry]")
        except Exception as e:
            print(f"  [error reading key: {e}]")
        print("--------------------")


# End of file. There is no additional code following dump_memories.

