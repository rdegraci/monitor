"""Data and preprocessing helper commands for built-in command dispatch."""

import logging
from typing import Any

from monitor.lib.display_output import print_colored_error

logger = logging.getLogger(__name__)


def clean_missing_values_command(args: Any) -> Any:
    """Clean missing values in the specified file.

    Args:
        args: Either None, a help string, a file path string, or a dict with
            ``file_path`` and optional ``fill_value``.

    Returns:
        The preprocessing result on success, an error string on failure, or
        None when showing help.
    """
    from monitor.lib.preprocessing import clean_missing_values

    usage = (
        "Usage: clean_missing_values_command(<file_path>)\n"
        "   or clean_missing_values_command({'file_path': <path>, 'fill_value': <value>})\n"
        "If 'help' or None is provided, this message is printed."
    )

    if args is None:
        print(usage)
        return None

    if isinstance(args, str):
        arg_str = args.strip()
        if not arg_str or arg_str.lower() in {"help", "?", "-h", "--help"}:
            print(usage)
            return None
        file_path = arg_str
        fill_value = 0
    elif isinstance(args, dict):
        if args.get("help"):
            print(usage)
            return None
        file_path = args.get("file_path")
        fill_value = args.get("fill_value", 0)
        if not file_path:
            print_colored_error("Missing required parameter: 'file_path'")
            logger.error(
                "Missing required parameter 'file_path' in "
                "clean_missing_values_command call."
            )
            return None
    else:
        print_colored_error(
            "Invalid argument type. Provide a file path string or a dict with "
            "'file_path'."
        )
        logger.error(
            "Invalid argument type for clean_missing_values_command: %s",
            type(args),
        )
        return None

    try:
        result = clean_missing_values(file_path, fill_value)
        return result
    except Exception as exc:
        logger.error("Error in clean_missing_values_command: %s", exc, exc_info=True)
        return f"Error cleaning missing values: {exc}"


def normalize_data_command(args: Any) -> Any:
    """Normalize data in the specified file.

    Args:
        args: Either None, a help string, a file path string, or a dict with
            ``file_path`` and optional ``method``.

    Returns:
        The preprocessing result on success, an error string on failure, or
        None when showing help.
    """
    from monitor.lib.preprocessing import normalize_data

    usage = (
        "Usage: normalize_data_command(<file_path>)\n"
        "   or normalize_data_command({'file_path': <path>, 'method': <method>})\n"
        "If 'help' or None is provided, this message is printed."
    )

    if args is None:
        print(usage)
        return None

    if isinstance(args, str):
        arg_str = args.strip()
        if not arg_str or arg_str.lower() in {"help", "?", "-h", "--help"}:
            print(usage)
            return None
        file_path = arg_str
        method = "standard"
    elif isinstance(args, dict):
        if args.get("help"):
            print(usage)
            return None
        file_path = args.get("file_path")
        method = args.get("method", "standard")
        if not file_path:
            print_colored_error("Missing required parameter: 'file_path'")
            logger.error(
                "Missing required parameter 'file_path' in normalize_data_command "
                "call."
            )
            return None
    else:
        print_colored_error(
            "Invalid argument type. Provide a file path string or a dict with "
            "'file_path'."
        )
        logger.error(
            "Invalid argument type for normalize_data_command: %s",
            type(args),
        )
        return None

    try:
        result = normalize_data(file_path, method)
        return result
    except Exception as exc:
        logger.error("Error in normalize_data_command: %s", exc, exc_info=True)
        return f"Error normalizing data: {exc}"
