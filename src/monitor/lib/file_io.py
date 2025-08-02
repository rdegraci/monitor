
"""
lib/file_io.py
Centralized File IO utilities for reading, writing, creating, deleting,
and checking files or directories.
All functions consistently handle errors and return user-friendly messages or exceptions,
with optional logging integration.

All file system interactions in the project should use these helpers for consistency.
"""
import os
import logging
import json
from typing import Optional

from monitor.lib.colors import print_yellow, print_blue, print_red, yellow, blue, red, reset

logger = logging.getLogger(__name__)

def file_exists(path: str) -> bool:
    """Checks if the specified path exists and is a file (not a directory).

    Args:
        path (str): Path to check.
    Returns:
        bool: True if it exists and is a file, False otherwise.
    """
    return os.path.isfile(path)

def read_file(path: str) -> Optional[str]:
    """Reads and returns the contents of the file at the given path.

    Args:
        path (str): Path to the file.
    Returns:
        str: File contents if successful, None if error occurred.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"{red}{e}{reset}")
        logger.error(f"Error reading file {path}: {e}")
        return None

def write_file(path: str, contents: str, overwrite: bool = True) -> bool:
    """Writes contents to the specified file. Optionally does not overwrite.

    Args:
        path (str): File path to write to.
        contents (str): Content to write.
        overwrite (bool): If False and file exists, will not overwrite.
    Returns:
        bool: True on success, False on error.
    """
    if not overwrite and os.path.exists(path):
        logger.warning(f"File already exists & overwrite=False: {path}")
        return False
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(contents)
        return True
    except Exception as e:
        print(f"{red}{e}{reset}")
        logger.error(f"Error writing file {path}: {e}")
        return False

def create_file(path: str, contents: str) -> bool:
    """Creates a file only if it does not exist. Writes contents.

    Args:
        path (str): Path for the new file.
        contents (str): Content to write.
    Returns:
        bool: True if file created, False otherwise.
    """
    return write_file(path, contents, overwrite=False)

def delete_file(path: str) -> bool:
    """Deletes a file at the specified path.

    Args:
       path (str): Path of the file to delete.
    Returns:
       bool: True if deleted, False otherwise.
    """
    try:
        os.remove(path)
        return True
    except Exception as e:
        print(f"{red}{e}{reset}")
        logger.error(f"Error deleting file {path}: {e}")
        return False

def list_directory(path: str) -> Optional[list]:
    """Returns a list of entries (files & folders) in the given directory.

    Args:
        path (str): Path to the directory.
    Returns:
        list | None: List of entry names, or None if error.
    """
    try:
        return sorted(os.listdir(path))
    except Exception as e:
        print(f"{red}{e}{reset}")
        logger.error(f"Error listing directory {path}: {e}")
        return None

def is_file(path: str) -> bool:
    """Checks if the specified path exists and is a file.

    Args:
        path (str): Path to check.

    Returns:
        bool: True if the path exists and is a file, False otherwise.
    """
    return os.path.isfile(path)

def is_directory(path: str) -> bool:
    """Checks if the specified path exists and is a directory.

    Args:
        path (str): Path to check.

    Returns:
        bool: True if the path exists and is a directory, False otherwise.
    """
    return os.path.isdir(path)

def make_dirs(path: str) -> None:
    """Creates parent directories for the given path if they do not exist.

    Args:
        path (str): The directory path to create.

    Returns:
        None
    """
    os.makedirs(path, exist_ok=True)


