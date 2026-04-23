"""Validation helpers for monitor function key configuration."""

from typing import Any

VALID_FUNCTION_KEYS = {f"F{i}" for i in range(1, 25)}


def validate_function_keys_config(function_keys: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Validate and normalize function key mappings.

    Args:
        function_keys: Raw mapping loaded from function_keys.json.

    Returns:
        A normalized mapping from function key names to configuration dicts.

    Raises:
        ValueError: If the configuration shape is invalid.
    """
    if not isinstance(function_keys, dict):
        raise ValueError("function_keys configuration must be a dictionary")

    normalized: dict[str, dict[str, str]] = {}
    for key_name, key_value in function_keys.items():
        normalized_key_name = key_name.upper()
        if normalized_key_name not in VALID_FUNCTION_KEYS:
            raise ValueError(f"Invalid function key name: {key_name}")
        if not isinstance(key_value, dict):
            raise ValueError(f"Function key '{key_name}' must map to an object")
        text_value = key_value.get("text")
        if not isinstance(text_value, str) or not text_value.strip():
            raise ValueError(f"Function key '{key_name}' must define a non-empty 'text' field")
        description_value = key_value.get("description", "")
        if not isinstance(description_value, str):
            raise ValueError(f"Function key '{key_name}' has an invalid 'description' field")
        normalized[normalized_key_name] = {
            "text": text_value,
            "description": description_value,
        }
    return normalized
