"""Local shims for optional third-party APIs used by monitor.lib."""
from __future__ import annotations

from typing import Any


def _load_attr(module_name: str, attr_name: str) -> Any:
    """Load an attribute from an optional dependency.

    Args:
        module_name: The import path of the optional dependency.
        attr_name: The attribute to access from the imported module.

    Returns:
        The requested attribute when available, otherwise None.
    """
    try:
        module = __import__(module_name, fromlist=[attr_name])
    except Exception:
        return None
    return getattr(module, attr_name, None)


Source: Any = _load_attr("graphviz", "Source")
ClassNotFound: Any = _load_attr("pygments.util", "ClassNotFound")
get_lexer_for_filename: Any = _load_attr("pygments.lexers", "get_lexer_for_filename")
TextLexer: Any = _load_attr("pygments.lexers", "TextLexer")
