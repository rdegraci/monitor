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
CODE_LENS_HOST=None
CODE_LENS_PORT=None 
JOKES_FILE=None 
JOKES = []
TWITTER_CLIENT_API=None
TWITCH_CLIENT_API=None 
LINKEDIN_CLIENT_API=None

def configure_external_services(
    artifact_server, 
    code_lens_host, 
    code_lens_port, 
    jokes_file,
    twitter_client_api=None,
    twitch_client_api=None,
    linkedin_client_api=None
    ):
    """Configure external service endpoints and related settings.

    This function initializes global configuration for external integrations
    used by the application, including the artifact server, code lens server,
    jokes file path, and social platform API endpoints. For social platform
    endpoints, if a value is not provided (None), a sensible local default
    will be used to maintain backward compatibility.

    Args:
        artifact_server (str): Base URL for the artifact server to which messages are sent.
        code_lens_host (str): Hostname or IP address for the Code Lens server.
        code_lens_port (str | int): Port number for the Code Lens server.
        jokes_file (str): Path to the file used for storing and de-duplicating jokes.
        twitter_client_api (str | None): Full URL for the Twitter client API endpoint.
            If None, defaults to http://localhost:7070/twitter/tweet.
        twitch_client_api (str | None): Full URL for the Twitch client API endpoint.
            If None, defaults to http://localhost:5050/send_message.
        linkedin_client_api (str | None): Full URL for the LinkedIn client API endpoint.
            If None, defaults to http://localhost:6060/linkedin/article.

    Behavior:
        - Sets module-level globals for all provided services.
        - Applies default local endpoints for any social platform API parameter that is None.
        - Intended to be called once during application initialization, but can be called
          again to update configurations at runtime.
    """
    global ARTIFACT_SERVER, CODE_LENS_HOST, CODE_LENS_PORT, JOKES_FILE
    global TWITTER_CLIENT_API, TWITCH_CLIENT_API, LINKEDIN_CLIENT_API

    ARTIFACT_SERVER = artifact_server
    CODE_LENS_HOST = code_lens_host
    CODE_LENS_PORT = code_lens_port
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

def send_file_to_indexing_service(file_path):
    """
    Reads the contents of the file at file_path and sends a POST request
    to the Code Lens server's /embed_source endpoint with the file name and contents.

    Parameters:
      file_path (str): The path to the file.
      server_url (str): The URL of the Flask endpoint.
      
    Returns:
      dict: The JSON response from the server.
    """
    logger.debug("Entering send_file_to_indexing_service function with file: %s", file_path)
    
    server_url=f'http://{CODE_LENS_HOST}:{CODE_LENS_PORT}/embed_source'

    try:
        with open(file_path, 'r') as f:
            file_contents = f.read()
        logger.debug("Successfully read file contents: %s", file_path)
    except Exception as e:
        logger.error("Failed to read file %s: %s", file_path, str(e), exc_info=True)
        return None

    file_name = os.path.basename(file_path)
    payload = {
        "file_name": file_name,
        "source_code": file_contents
    }

    try:
        logger.info("Sending file %s to indexing service at %s", file_name, server_url)
        response = requests.post(server_url, json=payload, timeout=30)
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

def send_analyze_request_to_indexing_service(query):
    """
    Sends a query string to the Code Lens server's /query endpoint.

    Parameters:
      query (str): The natural language query.
      server_url (str): The URL of the Flask /query endpoint.

    Returns:
      dict: The JSON response from the server if successful, otherwise None.
    """
    logger.debug("Entering send_analyze_request_to_indexing_service function with query: %s", query)
    
    server_url=f'http://{CODE_LENS_HOST}:{CODE_LENS_PORT}/analyze'

    payload = { "query": query }
    
    try:
        logger.info("Sending analysis request with query: %s", query)
        response = requests.post(server_url, json=payload, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            logger.info("Successfully retrieved augmented generation for analysis")
            print(f"{yellow}Successful retrieval-augmented generation. Waiting for LLM response...{reset}")
            print_all_metadata(data)
            return data
        else:
            logger.error("Failed to get successful analysis response: status_code=%s, response=%s", 
                        response.status_code, response.text)
            return None
    except Exception as e:
        logger.error("Error during analysis request: %s", str(e), exc_info=True)
        return None


def send_query_to_indexing_service(query):
    """
    Sends a query string to the Code Lens server's /query endpoint.

    Parameters:
      query (str): The natural language query.
      server_url (str): The URL of the Flask /query endpoint.

    Returns:
      dict: The JSON response from the server if successful, otherwise None.
    """
    logger.debug("Entering send_query_to_indexing_service function with query: %s", query)
    
    server_url=f'http://{CODE_LENS_HOST}:{CODE_LENS_PORT}/query'

    payload = { "query": query }
    
    try:
        logger.info("Sending query to indexing service: %s", query)
        response = requests.post(server_url, json=payload, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            logger.info("Successfully retrieved augmented generation for query")
            print(f"{yellow}Successful retrieval-augmented generation. Waiting for LLM response...{reset}")
            return data
        else:
            logger.error("Failed to get successful query response: status_code=%s, response=%s", 
                        response.status_code, response.text)
            return None
    except Exception as e:
        logger.error("Error during query request: %s", str(e), exc_info=True)
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
