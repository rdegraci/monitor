import logging
import os

from monitor._stubs import requests

from monitor import config
logger = logging.getLogger(__name__)

FILE_TYPE = [".swift", ".py", ".h", ".m", ".rb"]


def index_directory(directory_path, recursive=True):
    """Index all .swift and .py files in a directory.

    Args:
        directory_path (str): The path to the directory to index.
        recursive (bool, optional): Whether to recursively walk through subdirectories.
                                    Defaults to True.

    Yields:
        tuple: A tuple of (file_path, source_code) for each file found.
    """
    logger.debug("Starting directory indexing for path=%s with recursive=%s", directory_path, recursive)
    if recursive:
        for root, _, files in os.walk(directory_path):
            for file in files:
                if file.endswith(tuple(FILE_TYPE)):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            source_code = f.read()
                    except Exception as e:
                        logger.error("Error reading file %s: %s", file_path, e, exc_info=True)
                        continue
                    logger.debug("Indexed file %s with size %d bytes", file_path, len(source_code))
                    yield file_path, source_code
    else:
        try:
            for file in os.listdir(directory_path):
                file_path = os.path.join(directory_path, file)
                if os.path.isfile(file_path) and file.endswith(tuple(FILE_TYPE)):
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            source_code = f.read()
                    except Exception as e:
                        logger.error("Error reading file %s: %s", file_path, e, exc_info=True)
                        continue
                    logger.debug("Indexed file %s with size %d bytes", file_path, len(source_code))
                    yield file_path, source_code
        except Exception as e:
            logger.error("Error accessing directory %s: %s", directory_path, e, exc_info=True)


def send_to_embedding_service(file_path, source_code):
    """Sends the source file data to the embedding service.

    Args:
        file_path (str): The path of the file being sent.
        source_code (str): The code content of the file.
    """
    logger.debug("Sending file %s to embedding service", file_path)
    payload = {
        "file_name": file_path,
        "source_code": source_code
    }
    try:
        timeout = getattr(config, "EMBEDCODESERV_TIMEOUT", None) or 90
        url = f"http://{config.EMBEDCODESERV_HOST}:{config.EMBEDCODESERV_PORT}/embed_source"
        response = requests.post(url, json=payload, timeout=timeout)
        if response.status_code == 202:
            logger.info("Successfully queued embedding for file: %s", file_path)
        else:
            logger.warning("Failed to queue embedding for file: %s. Status code: %s. Response: %s", 
                         file_path, response.status_code, response.text)
    except requests.exceptions.RequestException as e:
        logger.error("HTTP request error while embedding file %s: %s", file_path, e, exc_info=True)


def embed_directory(directory_path, recursive=True):
    """Indexes a directory (with optional recursion) and sends all found .swift and .py files to the embedding service.

    Args:
        directory_path (str): The path of the directory to process.
        recursive (bool, optional): Whether to recursively walk through subdirectories.
                                    Defaults to True.
    """
    logger.debug("Starting embedding process for directory %s with recursive=%s", directory_path, recursive)
    for file_path, source_code in index_directory(directory_path, recursive):
        send_to_embedding_service(file_path, source_code)


