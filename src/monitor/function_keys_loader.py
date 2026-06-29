"""Loader for monitor function key configuration."""

import json
import logging
import os

from monitor._stubs import appdirs

from monitor.function_keys import validate_function_keys_config

LOGGER = logging.getLogger(__name__)


def find_config_file(filename):
    """Find a monitor configuration file.

    Args:
        filename: Configuration file name to locate.

    Returns:
        Absolute path to the first matching configuration file.

    Raises:
        RuntimeError: If the file cannot be located or an unexpected error occurs.
    """
    try:
        config_dir = appdirs.user_config_dir("monitor")
        candidate_paths = (
            os.path.join(config_dir, filename),
            os.path.join(os.getcwd(), filename),
        )
        for candidate_path in candidate_paths:
            if os.path.exists(candidate_path):
                return candidate_path
        raise FileNotFoundError(filename)
    except FileNotFoundError as exc:
        LOGGER.error("Unable to locate %s: %s", filename, exc, exc_info=True)
        raise RuntimeError(f"Unable to locate {filename}") from exc
    except OSError as exc:
        LOGGER.error("Unable to locate %s: %s", filename, exc, exc_info=True)
        raise RuntimeError(f"Unable to locate {filename}") from exc
    except Exception as exc:
        LOGGER.error("Unable to locate %s: %s", filename, exc, exc_info=True)
        raise RuntimeError(f"Unable to locate {filename}") from exc


def load_function_keys_config(file_path=None):
    """Load and validate function key configuration.

    Args:
        file_path: Optional path to function_keys.json or config directory.

    Returns:
        Normalized function key group mapping.

    Raises:
        RuntimeError: If the file is missing, invalid, or fails validation.
    """
    try:
        config_path = file_path or find_config_file("function_keys.json")
    except Exception as exc:
        LOGGER.error("Unable to locate function_keys.json: %s", exc, exc_info=True)
        raise RuntimeError("Unable to locate function_keys.json") from exc

    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            raw_config = json.load(handle)
    except FileNotFoundError as exc:
        LOGGER.error("function_keys.json not found: %s", config_path, exc_info=True)
        raise RuntimeError("function_keys.json not found") from exc
    except json.JSONDecodeError as exc:
        LOGGER.error("Malformed function_keys.json at %s: %s", config_path, exc, exc_info=True)
        raise RuntimeError("Malformed function_keys.json") from exc
    except OSError as exc:
        LOGGER.error("Unable to read function_keys.json at %s: %s", config_path, exc, exc_info=True)
        raise RuntimeError("Unable to read function_keys.json") from exc

    try:
        return validate_function_keys_config(raw_config)
    except Exception as exc:
        LOGGER.error("Invalid function key configuration at %s: %s", config_path, exc, exc_info=True)
        raise RuntimeError("Invalid function key configuration") from exc
