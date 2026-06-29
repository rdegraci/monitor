"""Local typing helpers for optional third-party dependencies."""
from __future__ import annotations

from typing import Any

from importlib import import_module


def _load_optional(name: str) -> Any:
    """Import an optional dependency and return a typed fallback on failure."""
    try:
        return import_module(name)
    except Exception:
        return None


appdirs: Any = _load_optional("appdirs")
pyperclip: Any = _load_optional("pyperclip")
requests: Any = _load_optional("requests")
yaml: Any = _load_optional("yaml")
