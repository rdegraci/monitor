"""Typing helpers for optional pygments imports."""
from __future__ import annotations

from typing import Any

from importlib import import_module


def _load_optional_attr(module_name: str, attribute_name: str) -> Any:
    """Import an optional module attribute and return ``None`` if unavailable."""
    try:
        module = import_module(module_name)
        return getattr(module, attribute_name)
    except Exception:
        return None


highlight: Any = _load_optional_attr("pygments", "highlight")
TerminalFormatter: Any = _load_optional_attr("pygments.formatters", "TerminalFormatter")
MarkdownLexer: Any = _load_optional_attr("pygments.lexers", "MarkdownLexer")
BashLexer: Any = _load_optional_attr("pygments.lexers", "BashLexer")
DiffLexer: Any = _load_optional_attr("pygments.lexers", "DiffLexer")
SwiftLexer: Any = _load_optional_attr("pygments.lexers", "SwiftLexer")
