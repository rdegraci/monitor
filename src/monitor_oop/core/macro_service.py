"""Macro service for Monitor OOP."""
from __future__ import annotations


class MacroService:
    """Owns macro definitions and expansion state."""

    def __init__(self, config_service) -> None:
        self.config_service = config_service
        self.macros: dict[str, str] = {}

    def load(self) -> None:
        """Load macros for this runtime."""

        return None

    def expand(self, text: str) -> str:
        """Expand macros in ``text``."""

        return text

    def add_definition(self, raw_text: str) -> bool:
        """Add a macro definition from raw text."""

        parts = raw_text.split("=", maxsplit=1)
        if len(parts) != 2:
            return False
        key, value = (part.strip() for part in parts)
        if not key:
            return False
        self.macros[key] = value
        return True

    def list_macros(self) -> dict[str, str]:
        """Return all known macros."""

        return dict(self.macros)

    def reload(self) -> None:
        """Reload macros from configuration."""

        self.load()
