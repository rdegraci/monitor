"""Validation helpers for monitor function key configuration."""

from collections.abc import Mapping
from typing import Any

VALID_FUNCTION_KEYS = {f"F{i}" for i in range(1, 9)}
RESERVED_FUNCTION_KEYS = {f"F{i}" for i in range(9, 13)}


def validate_function_keys_config(
    function_keys: dict[str, Any],
) -> dict[str, dict[str, dict[str, str]]]:
    """Validate and normalize grouped function key mappings.

    Args:
        function_keys: Raw mapping loaded from function_keys.json.

    Returns:
        A normalized mapping from group names to function key configuration dicts.

    Raises:
        ValueError: If the configuration shape is invalid.
    """
    if not isinstance(function_keys, dict):
        raise ValueError("function_keys configuration must be a dictionary of groups")

    normalized: dict[str, dict[str, dict[str, str]]] = {}

    for group_name, group_value in function_keys.items():
        if not isinstance(group_name, str) or not group_name.strip():
            raise ValueError("Group names must be non-empty strings")
        if not isinstance(group_value, Mapping):
            raise ValueError(f"Group '{group_name}' must map to an object")

        normalized_group_name = group_name
        normalized_group: dict[str, dict[str, str]] = {}

        for key_name, key_value in group_value.items():
            if not isinstance(key_name, str):
                raise ValueError(f"Group '{group_name}' contains a non-string function key name")
            normalized_key_name = key_name.upper()
            if normalized_key_name in RESERVED_FUNCTION_KEYS:
                raise ValueError(
                    f"Group '{group_name}' uses reserved function key '{normalized_key_name}'"
                )
            if normalized_key_name not in VALID_FUNCTION_KEYS:
                raise ValueError(
                    f"Group '{group_name}' contains invalid function key '{key_name}'"
                )
            if not isinstance(key_value, Mapping):
                raise ValueError(f"Function key '{key_name}' in group '{group_name}' must map to an object")

            text_value = key_value.get("text")
            if not isinstance(text_value, str) or not text_value.strip():
                raise ValueError(
                    f"Function key '{key_name}' in group '{group_name}' must define a non-empty 'text' field"
                )

            description_value = key_value.get("description")
            if not isinstance(description_value, str) or not description_value.strip():
                raise ValueError(
                    f"Function key '{key_name}' in group '{group_name}' must define a non-empty 'description' field"
                )

            normalized_group[normalized_key_name] = {
                "text": text_value,
                "description": description_value,
            }

        normalized[normalized_group_name] = normalized_group

    return normalized
