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
    try:
        if os.path.islink(path):
            link_target = os.readlink(path)
            if not os.path.exists(os.path.join(os.path.dirname(path), link_target) if not os.path.isabs(link_target) else link_target):
                msg = f"Symlink detected at {path}, but target '{link_target}' does not exist (broken symlink)."
                print(f"{red}{msg}{reset}")
                logger.error(msg)
                return False
            msg = f"Symlink detected at {path}, points to '{link_target}'."
            print(f"{yellow}{msg}{reset}")
            logger.info(msg)
        return os.path.isfile(path)
    except OSError as e:
        msg = f"Error determining if file exists or handling symlink at {path}: {e}"
        print(f"{red}{msg}{reset}")
        logger.error(msg)
        return False

def read_file(path: str) -> Optional[str]:
    """Reads and returns the contents of the file at the given path.

    Args:
        path (str): Path to the file.
    Returns:
        str: File contents if successful, None if error occurred.
    """
    try:
        if os.path.islink(path):
            link_target = os.readlink(path)
            resolved_path = os.path.join(os.path.dirname(path), link_target) if not os.path.isabs(link_target) else link_target
            if not os.path.exists(resolved_path):
                msg = f"Symlink detected at {path}, target '{link_target}' does not exist (broken symlink). Cannot read."
                print(f"{red}{msg}{reset}")
                logger.error(msg)
                return None
            msg = f"Symlink detected at {path}, points to '{link_target}'. Attempting to read target."
            print(f"{yellow}{msg}{reset}")
            logger.info(msg)
            open_path = resolved_path
        else:
            open_path = path
        with open(open_path, 'r', encoding='utf-8') as f:
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
    try:
        if os.path.islink(path):
            link_target = os.readlink(path)
            resolved_path = os.path.join(os.path.dirname(path), link_target) if not os.path.isabs(link_target) else link_target
            if not os.path.exists(resolved_path):
                msg = f"Symlink detected at {path}, target '{link_target}' does not exist (broken symlink). Cannot write."
                print(f"{red}{msg}{reset}")
                logger.error(msg)
                return False
            msg = f"Symlink detected at {path}, points to '{link_target}'. Attempting to write to target."
            print(f"{yellow}{msg}{reset}")
            logger.info(msg)
            write_target = resolved_path
        else:
            write_target = path

        if not overwrite and os.path.exists(write_target):
            if os.path.islink(path):
                logger.warning(f"Symlink {path} (target {write_target}) already exists & overwrite=False")
            else:
                logger.warning(f"File already exists & overwrite=False: {write_target}")
            return False
        with open(write_target, 'w', encoding='utf-8') as f:
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
        if os.path.islink(path):
            link_target = os.readlink(path)
            resolved_path = os.path.join(os.path.dirname(path), link_target) if not os.path.isabs(link_target) else link_target
            msg = f"Symlink detected at {path}, points to '{link_target}'. Attempting to delete symlink (not target)."
            print(f"{yellow}{msg}{reset}")
            logger.info(msg)
            # We remove the symlink itself, not the target
            os.remove(path)
            return True
        else:
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
        if os.path.islink(path):
            link_target = os.readlink(path)
            resolved_path = os.path.join(os.path.dirname(path), link_target) if not os.path.isabs(link_target) else link_target
            if not os.path.exists(resolved_path):
                msg = f"Symlink detected at {path}, target '{link_target}' does not exist (broken symlink). Cannot list directory."
                print(f"{red}{msg}{reset}")
                logger.error(msg)
                return None
            msg = f"Symlink detected at {path}, points to '{link_target}'. Attempting to list entries in target directory."
            print(f"{yellow}{msg}{reset}")
            logger.info(msg)
            list_path = resolved_path
        else:
            list_path = path
        return sorted(os.listdir(list_path))
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
    try:
        if os.path.islink(path):
            link_target = os.readlink(path)
            resolved_path = os.path.join(os.path.dirname(path), link_target) if not os.path.isabs(link_target) else link_target
            if not os.path.exists(resolved_path):
                msg = f"Symlink detected at {path}, but target '{link_target}' does not exist (broken symlink)."
                print(f"{red}{msg}{reset}")
                logger.error(msg)
                return False
            msg = f"Symlink detected at {path}, points to '{link_target}'."
            print(f"{yellow}{msg}{reset}")
            logger.info(msg)
        return os.path.isfile(path)
    except OSError as e:
        msg = f"Error determining if file or symlink at {path}: {e}"
        print(f"{red}{msg}{reset}")
        logger.error(msg)
        return False

def is_directory(path: str) -> bool:
    """Checks if the specified path exists and is a directory.

    Args:
        path (str): Path to check.

    Returns:
        bool: True if the path exists and is a directory, False otherwise.
    """
    try:
        if os.path.islink(path):
            link_target = os.readlink(path)
            resolved_path = os.path.join(os.path.dirname(path), link_target) if not os.path.isabs(link_target) else link_target
            if not os.path.exists(resolved_path):
                msg = f"Symlink detected at {path}, but target '{link_target}' does not exist (broken symlink)."
                print(f"{red}{msg}{reset}")
                logger.error(msg)
                return False
            msg = f"Symlink detected at {path}, points to '{link_target}'."
            print(f"{yellow}{msg}{reset}")
            logger.info(msg)
        return os.path.isdir(path)
    except OSError as e:
        msg = f"Error determining if directory or symlink at {path}: {e}"
        print(f"{red}{msg}{reset}")
        logger.error(msg)
        return False

def make_dirs(path: str) -> None:
    """Creates parent directories for the given path if they do not exist.

    Args:
        path (str): The directory path to create.

    Returns:
        None
    """
    os.makedirs(path, exist_ok=True)
