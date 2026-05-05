"""Macro service for Monitor OOP."""
from __future__ import annotations

import logging

from monitor_oop.core.infrastructure.macro_expander import MacroExpander
from monitor_oop.core.infrastructure.macro_store import MacroStore

logger = logging.getLogger(__name__)


class MacroService:
    """Owns macro definitions and expansion state."""

    def __init__(
        self,
        config_service,
        store: MacroStore,
        expander: MacroExpander,
    ) -> None:
        """Initialize the macro service with required dependencies."""
        self.config_service = config_service
        self._store = store
        self._expander = expander
        self._macros: dict[str, str] = {}
        logger.debug(
            "MacroService initialized with store=%s expander=%s",
            type(self._store).__name__,
            type(self._expander).__name__,
        )

    def load(self) -> None:
        """Load macros for this runtime."""

        logger.info("Loading macros for runtime")
        loaded_macros = self._store.load()
        self._macros = loaded_macros if loaded_macros is not None else {}
        logger.debug("Loaded %d macros: %s", len(self._macros), sorted(self._macros))

    def expand(self, text: str) -> str:
        """Expand macros in ``text``."""

        logger.info("Expanding text using %d macros", len(self._macros))
        logger.debug("Expand input text: %r", text)
        expanded = self._expander.expand(text, self._macros)
        logger.info("Expanded text: %r", expanded)
        logger.debug("Expand output text: %r", expanded)
        return expanded

    def add_definition(self, raw_text: str) -> bool:
        """Add a macro definition from raw text."""

        logger.info("Adding macro definition from raw text")
        logger.debug("Raw macro definition input: %r", raw_text)
        parts = raw_text.split("=", maxsplit=1)
        if len(parts) != 2:
            logger.debug("Rejected macro definition because it is not a key=value pair")
            return False
        key, value = (part.strip() for part in parts)
        if not key:
            logger.debug("Rejected macro definition because the key is empty")
            return False
        self._macros[key] = value
        logger.debug("Stored macro %r with value %r; total macros=%d", key, value, len(self._macros))
        self._store.save(self._macros)
        logger.info("Added macro definition for key=%r", key)
        return True

    def list_macros(self) -> dict[str, str]:
        """Return all known macros."""

        return dict(self._macros)

    def reload(self) -> None:
        """Reload macros from configuration."""

        logger.info("Reloading macros from configuration")
        self.load()
