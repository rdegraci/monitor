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
joblib: Any = _load_optional("joblib")
np: Any = _load_optional("numpy")
pandas: Any = _load_optional("pandas")
pyperclip: Any = _load_optional("pyperclip")
pyaudio: Any = _load_optional("pyaudio")
requests: Any = _load_optional("requests")
tavily_module: Any = _load_optional("tavily")
TavilyClient: Any = getattr(tavily_module, "TavilyClient", None)
whisper: Any = _load_optional("whisper")
yaml: Any = _load_optional("yaml")
