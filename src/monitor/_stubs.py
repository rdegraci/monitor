"""Local typing helpers for optional third-party dependencies."""
from __future__ import annotations

from typing import Any

from monitor.lib.optional_deps import load_optional


appdirs: Any = load_optional("appdirs")
joblib: Any = load_optional("joblib")
np: Any = load_optional("numpy")
pandas: Any = load_optional("pandas")
pyperclip: Any = load_optional("pyperclip")
pyaudio: Any = load_optional("pyaudio")
requests: Any = load_optional("requests")
tavily_module: Any = load_optional("tavily")
TavilyClient: Any = getattr(tavily_module, "TavilyClient", None) if tavily_module else None
whisper: Any = load_optional("whisper")
yaml: Any = load_optional("yaml")
