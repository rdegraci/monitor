import logging
import litellm
import requests
import json
import os


from pygments import highlight
from pygments.lexers import BashLexer, MarkdownLexer, DiffLexer, SwiftLexer
from pygments.formatters import TerminalFormatter

from monitor.lib.colors import red, yellow, blue, reset

logger = logging.getLogger(__name__)

from monitor import config

DEFAULT_HTTP_TIMEOUT = 30

ARTIFACT_SERVER=None
JOKES_FILE=None
JOKES = []
TWITTER_CLIENT_API=None
TWITCH_CLIENT_API=None
LINKEDIN_CLIENT_API=None


def _embedcodeserv_base_url():
    """Construct the embedcodeserv base URL from the live config. Read at
    each call so a runtime config change picks up without reconfiguration.
    Returns e.g. 'http://192.168.0.250:5010' (no trailing slash)."""
    return f"http://{config.EMBEDCODESERV_HOST}:{config.EMBEDCODESERV_PORT}"


def _embedcodeserv_timeout():
    """Return the configured embedcodeserv request timeout (seconds),
    defaulting to 30 when the config global is None/invalid."""
    val = getattr(config, "EMBEDCODESERV_TIMEOUT", None)
    if isinstance(val, int) and val > 0:
        return val
    return 30


def configure_external_services(
    artifact_server,
    jokes_file,
    twitter_client_api=None,
    twitch_client_api=None,
    linkedin_client_api=None
    ):
    """Configure external service endpoints and related settings.

    Initializes module-level globals for external integrations. embedcodeserv
    (indexing/retrieval) config is read directly from monitor.config at call
    time and is NOT passed in here.

    Args:
        artifact_server (str): Base URL for the artifact server.
        jokes_file (str): Path to the jokes storage file.
        twitter_client_api (str | None): Twitter API URL, falls back to local default.
        twitch_client_api (str | None): Twitch API URL, falls back to local default.
        linkedin_client_api (str | None): LinkedIn API URL, falls back to local default.
    """
    global ARTIFACT_SERVER, JOKES_FILE
    global TWITTER_CLIENT_API, TWITCH_CLIENT_API, LINKEDIN_CLIENT_API

    ARTIFACT_SERVER = artifact_server
    JOKES_FILE = jokes_file
    TWITTER_CLIENT_API = twitter_client_api if twitter_client_api is not None else "http://localhost:7070/twitter/tweet"
    TWITCH_CLIENT_API = twitch_client_api if twitch_client_api is not None else "http://localhost:5050/send_message"
    LINKEDIN_CLIENT_API = linkedin_client_api if linkedin_client_api is not None else "http://localhost:6060/linkedin/article"

def send_artifact(message: str):
    """Send a message to Artifact server."""
    logger.debug("Entering send_artifact function")
    
    if not config.EXTERNAL_SERVICES:
        logger.info("Artifact message not sent. No external services allowed.")
        return

    if not message:
        logger.warning("Artifact message not provided - cannot send empty message")
        return
    
    url = ARTIFACT_SERVER
    data = {"text": message}

    try:
        response = requests.post(url, json=data, timeout=DEFAULT_HTTP_TIMEOUT)
        
        # Check if the request was successful
        if response.status_code == 200:
            logger.info("Artifact message sent successfully")
        else:
            logger.error("Failed to send artifact message: status_code=%s, response=%s", 
                         response.status_code, response.text)
    except requests.exceptions.RequestException as e:
        logger.error("Error occurred when sending artifact message: %s", str(e), exc_info=True)


def send_twitter_message(message: str) -> None:
    """Send a message to Twitter."""
    logger.debug("Entering send_twitter_message function")
    
    if not message:
        logger.warning("Twitter message not provided - cannot send empty message")
        return

    if not TWITTER_CLIENT_API:
        logger.warning("Twitter API endpoint is not configured - cannot send message")
        return
    
    data = {"text": message}

    try:
        response = requests.post(TWITTER_CLIENT_API, json=data, timeout=DEFAULT_HTTP_TIMEOUT)
        
        # Check if the request was successful
        if response.status_code == 201:
            logger.info("Twitter message sent successfully")
        else:
            logger.error("Failed to send Twitter message: status_code=%s, response=%s", 
                         response.status_code, response.text)
    except requests.exceptions.RequestException as e:
        logger.error("Error occurred when sending Twitter message: %s", str(e), exc_info=True)


def send_twitch_message_command(message: str) -> None:
    """Send a message to a specified Twitch channel. This function logs errors and returns without raising exceptions."""
    logger.debug("Entering send_twitch_message_command function")
    
    if not message:
        logger.warning("Twitch message not provided - cannot send empty message")
        return

    if not TWITCH_CLIENT_API:
        logger.warning("Twitch API endpoint is not configured - cannot send message")
        return
    
    data = {"message": message}

    try:
        response = requests.post(TWITCH_CLIENT_API, json=data, timeout=DEFAULT_HTTP_TIMEOUT)
        
        # Check if the request was successful
        if response.status_code == 200:
            logger.info("Twitch message sent successfully")
        else:
            logger.error("Failed to send Twitch message: status_code=%s, response=%s", 
                         response.status_code, response.text)
    except requests.exceptions.RequestException as e:
        logger.error("Error occurred when sending Twitch message: %s", str(e), exc_info=True)


def send_linkedin_message(message: str) -> None:
    """Send a message to LinkedIn."""
    logger.debug("Entering send_linkedin_message function")
    
    if not message:
        logger.warning("LinkedIn message not provided - cannot send empty message")
        return

    if not LINKEDIN_CLIENT_API:
        logger.warning("LinkedIn API endpoint is not configured - cannot send message")
        return
    
    data = {"text": message}

    try:
        response = requests.post(LINKEDIN_CLIENT_API, json=data, timeout=DEFAULT_HTTP_TIMEOUT)
        
        # Check if the request was successful
        if response.status_code == 200:
            logger.info("LinkedIn message sent successfully")
        else:
            logger.error("Failed to send LinkedIn message: status_code=%s, response=%s", 
                         response.status_code, response.text)
    except requests.exceptions.RequestException as e:
        logger.error("Error occurred when sending LinkedIn message: %s", str(e), exc_info=True)

def joke_for_twitch(arg=""):
    """Generate and send a joke to Twitch, ensuring no repetition."""
    logger.debug("Entering joke_for_twitch function")
    
    if JOKES_FILE is None:
        logger.warning("Jokes file not configured, skipping joke generation")
        return

    # Load already told jokes from the file
    try:
        with open(JOKES_FILE, "r") as f:
            JOKES.extend([line.strip() for line in f.readlines()])
        logger.debug("Successfully loaded %d jokes from file", len(JOKES))
    except FileNotFoundError:
        # If the file doesn't exist yet, an empty list is used
        logger.info("Jokes file not found at %s, starting with empty joke history", JOKES_FILE)
        pass
    
    instructions = f"""
    Here are some jokes you've already told: {JOKES}
    Tell a random witty joke, that you'ever told before.
    Limit the joke to at most 450 characters.
    """
    try:
        logger.info("Requesting joke generation from LLM model: %s", config.MODEL)
        response = litellm.completion(
            model=config.MODEL,
            messages=[
                {"role": "system", "content": f"You are a great comedian."},
                {"role": "user", "content": instructions}
            ],
            temperature=0.9,
            top_p=0.9
        )
    except Exception as e:
        logger.error("Error during joke generation with LLM: %s", str(e), exc_info=True)
        return
    
    summary = response.choices[0].message['content']
    
    # Output the joke to the terminal with colored output
    logger.info("Generated joke: %s", summary)
    print(f"{blue}Generated joke: {reset}{summary}")

    # Here we'd normally send the joke and store it in a file
    send_twitch_message_command(summary)
    try:
        with open(JOKES_FILE, "a") as f:
            f.write(summary + "\n")
        logger.debug("Successfully saved joke to history file: %s", JOKES_FILE)
    except Exception as e:
        logger.warning("Failed to save joke to history file: %s", str(e), exc_info=True)
    
    JOKES.append(summary)

def send_file_to_indexing_service(file_path, chunk_type=None, symbol_name=None, doc_comment=None):
    """
    POST a file's contents to embedcodeserv's /embed_source endpoint.

    Optional metadata fields (per the embedcodeserv API contract) are sent
    only when the caller provides them — letting the harness pass richer
    indexing hints (e.g. chunk_type="file" for whole-file embeddings) while
    still defaulting to file_name + source_code only.

    Args:
        file_path (str): Path to the file to embed.
        chunk_type (str, optional): e.g. "file", "function", or a SourceKitten
            kind. Defaults to None (omit from payload).
        symbol_name (str, optional): e.g. "greetUser". Defaults to None.
        doc_comment (str, optional): Doc comment / docstring. Defaults to None.

    Returns:
        dict | None: The server's 202 JSON response, or None on failure.
    """
    logger.debug("Entering send_file_to_indexing_service function with file: %s", file_path)

    # Surface a project-mismatch warning (e.g., trying to embed a .py file
    # while the server is running EMBED_PROJECT=swift). Non-fatal — we let
    # the call proceed so the user can intentionally embed cross-language
    # files; we just flag the likely mistake.
    warning = check_active_project_match(file_path)
    if warning:
        print(f"{yellow}WARNING: {warning}{reset}")

    server_url = f"{_embedcodeserv_base_url()}/embed_source"

    try:
        # encoding='utf-8' instead of platform default so source files with
        # non-ASCII content (typical on macOS/Linux UTF-8 locales, broken on
        # Windows with legacy code pages) read consistently.
        with open(file_path, "r", encoding="utf-8") as f:
            file_contents = f.read()
        logger.debug("Successfully read file contents: %s", file_path)
    except Exception as e:
        logger.error("Failed to read file %s: %s", file_path, str(e), exc_info=True)
        return None

    file_name = os.path.basename(file_path)
    payload = {
        "file_name": file_name,
        "source_code": file_contents,
    }
    # Per the embedcodeserv API, chunk_type/symbol_name/doc_comment are
    # optional. Only include them when callers supply something; sending
    # null/empty would still be valid but adds payload noise.
    if chunk_type is not None:
        payload["chunk_type"] = chunk_type
    if symbol_name is not None:
        payload["symbol_name"] = symbol_name
    if doc_comment is not None:
        payload["doc_comment"] = doc_comment

    try:
        logger.info("Sending file %s to indexing service at %s", file_name, server_url)
        response = requests.post(server_url, json=payload, timeout=_embedcodeserv_timeout())
        if response.status_code == 202:
            data = response.json()
            logger.info("Successfully sent file %s to indexing service", file_name)
            print(f"{blue}Successfully sent file. Server response:{reset}", data)
            return data
        else:
            logger.error("Failed to send file %s to indexing service: status_code=%s, response=%s",
                        file_name, response.status_code, response.text)
            return None
    except Exception as e:
        logger.error("Error during file indexing request: %s", str(e), exc_info=True)
        return None

def send_analyze_request_to_indexing_service(query_text, prompt):
    """POST embedcodeserv's /analyze endpoint (server-side RAG).

    The server retrieves relevant code chunks for ``query_text`` and runs
    them plus ``prompt`` through Ollama to produce an ``analysis`` string —
    all in one round trip. This is the first-class RAG path; clients should
    use this instead of doing client-side retrieval+generation.

    Args:
        query_text (str): Text used to retrieve relevant code chunks.
        prompt (str): Instruction sent to the LLM along with the retrieved code.

    Returns:
        dict | None: The 200-OK JSON body with ``results`` and ``analysis``,
        or None on failure / network error.
    """
    logger.debug("Entering send_analyze_request_to_indexing_service: query_text=%s", query_text)
    server_url = f"{_embedcodeserv_base_url()}/analyze"
    payload = {"query_text": query_text, "prompt": prompt}
    try:
        logger.info("Sending /analyze request with query_text=%s", query_text)
        response = requests.post(server_url, json=payload, timeout=_embedcodeserv_timeout())
        if response.status_code == 200:
            data = response.json()
            logger.info("Successfully retrieved retrieval-augmented analysis")
            return data
        else:
            logger.error("Failed /analyze response: status_code=%s, response=%s",
                        response.status_code, response.text)
            return None
    except Exception as e:
        logger.error("Error during /analyze request: %s", str(e), exc_info=True)
        return None


def send_query_to_indexing_service(query, comment_top_k=None):
    """POST embedcodeserv's /query endpoint (semantic search, no LLM).

    Returns retrieved chunks with raw_code_full, distance (cosine), and
    optionally commented_code on the top-K entries.

    Args:
        query (str): Natural-language search text.
        comment_top_k (int, optional): How many top results to LLM-comment.
            Server default is 3; pass 0 to disable commenting entirely for
            a faster response.

    Returns:
        dict | None: The 200-OK JSON body with ``results``, or None on failure.
    """
    logger.debug("Entering send_query_to_indexing_service: query=%s, comment_top_k=%s",
                 query, comment_top_k)
    server_url = f"{_embedcodeserv_base_url()}/query"
    payload = {"query": query}
    if isinstance(comment_top_k, int) and comment_top_k >= 0:
        payload["comment_top_k"] = comment_top_k

    try:
        logger.info("Sending /query request: %s", query)
        response = requests.post(server_url, json=payload, timeout=_embedcodeserv_timeout())
        if response.status_code == 200:
            data = response.json()
            logger.info("Successfully retrieved /query response")
            return data
        else:
            logger.error("Failed /query response: status_code=%s, response=%s",
                        response.status_code, response.text)
            return None
    except Exception as e:
        logger.error("Error during query request: %s", str(e), exc_info=True)
        return None


def get_embedcodeserv_info():
    """GET embedcodeserv's root endpoint for service info.

    Per the API, returns a JSON body with at least ``status``, ``service``,
    ``active_project``, and ``active_language`` — the last two report which
    per-project vector DB the running server is serving. The harness uses
    that to warn the user when their working file types (e.g., .py) don't
    match the server's active language (e.g., "swift").

    Uses a short timeout (5s) since this is a startup/sanity-check call,
    not a query — we don't want startup to hang on an unreachable server.

    Returns:
        dict | None: The JSON body on 200, None on failure or non-200.
    """
    server_url = f"{_embedcodeserv_base_url()}/"
    try:
        response = requests.get(server_url, timeout=5)
        if response.status_code == 200:
            return response.json()
        logger.debug("embedcodeserv GET / returned %s; ignoring.", response.status_code)
        return None
    except Exception as e:
        logger.debug("embedcodeserv GET / unreachable: %s", e)
        return None


# Session-scoped cache for the embedcodeserv GET / response. Populated on
# first use; subsequent calls return the cached info. None means "not yet
# fetched" (initial state) or "unreachable on the last attempt". The
# harness only calls GET / from :embed/:index/:query entry points, so this
# cache typically gets populated once per session.
_CACHED_SERVER_INFO = None


def _cached_server_info(force_refresh=False):
    """Return the cached embedcodeserv info dict, fetching on first call.

    Tests that need to force a re-fetch can pass ``force_refresh=True``.
    """
    global _CACHED_SERVER_INFO
    if force_refresh or _CACHED_SERVER_INFO is None:
        _CACHED_SERVER_INFO = get_embedcodeserv_info()
    return _CACHED_SERVER_INFO


# File-extension → embedcodeserv project-language mapping. Lets us warn
# when the user is trying to :embed a .py file while the server is running
# with EMBED_PROJECT=swift (different vector DB).
_EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".swift": "swift",
}


def check_active_project_match(file_path):
    """Compare a file's extension against the server's active_language and
    return a warning string when they mismatch, or None when everything's
    fine (or we can't tell).

    Args:
        file_path (str): The path being embedded/queried.

    Returns:
        str | None: A user-facing warning when a mismatch is detected;
        None when matched or undeterminable (server unreachable, unknown
        extension, etc.).
    """
    info = _cached_server_info()
    if not isinstance(info, dict):
        return None
    active_language = info.get("active_language")
    if not active_language:
        return None
    ext = os.path.splitext(file_path)[1].lower()
    expected = _EXTENSION_TO_LANGUAGE.get(ext)
    if expected is None:
        # Unknown extension — don't second-guess; server may handle it.
        return None
    if expected != active_language:
        return (
            f"embedcodeserv is running with active_language={active_language!r} "
            f"but the file extension {ext!r} maps to {expected!r}. The embedding "
            f"will go into the wrong vector DB. Restart the server with "
            f"EMBED_PROJECT={expected} to switch projects."
        )
    return None


def print_all_metadata(data):
    """
    Iterates over the metadatas in the given dictionary and prints the filename and summary for each.

    Args:
        data (dict): A dictionary containing at least the 'metadatas' key with nested metadata information.
    """
    logger.debug("Entering print_all_metadata function")
    
    metadatas = data.get("metadatas", [])
    if not metadatas:
        logger.info("No metadata available to print")
    
    for metadata_list in metadatas:
        for metadata in metadata_list:
            filename = metadata.get("filename", "Unknown filename")
            summary = metadata.get("summary", "No summary available")
            raw_code_full = metadata.get("raw_code_full", None)
            logger.debug("Printing metadata for file: %s", filename)
            print(f"Filename: {filename}")
            print(summary)
            # print("-" * 40)
            # if raw_code_full:
            #     highlighted_output = highlight(raw_code_full, SwiftLexer(), TerminalFormatter(reset=True))
            #     print(f"{highlighted_output}")
            # print("-" * 40)
            # print("-" * 40)
            # print("-" * 40)


def print_first_metadata(data):
    """
    Prints the first metadata item from the given dictionary. Assumes that the 'metadatas' key
    contains an array of metadata dictionaries.

    Args:
        data (dict): A dictionary containing at least the 'metadatas' key with metadata information.
    """
    logger.debug("Entering print_first_metadata function")
    
    metadatas = data.get("metadatas", [])
    if not metadatas:
        logger.warning("No metadata available to print")
        return

    # Assuming metadatas is a list of metadata dictionaries
    first_metadata = metadatas[0]
    
    filename = first_metadata.get("filename", "Unknown filename")
    summary = first_metadata.get("summary", "No summary available")
    raw_code_full = first_metadata.get("raw_code_full", "No code available")
    
    logger.info("Printing first metadata entry for file: %s", filename)
    print(f"Filename: {filename}")
    print(summary)
    print("-" * 40)
    print(raw_code_full)
