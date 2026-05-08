"""Runtime system prompt service for Monitor OOP."""
from __future__ import annotations

import logging

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.infrastructure.prompt_store import PromptStore

logger = logging.getLogger(__name__)


class PromptService:
    """Owns the resolved system prompt for one runtime instance."""

    def __init__(self, config_service: ConfigService, prompt_store: PromptStore) -> None:
        """Initialize the prompt service.

        Args:
            config_service: Runtime configuration service.
            prompt_store: Prompt store dependency.
        """
        self._config_service = config_service
        self._store = prompt_store
        self._prompt = ""
        logger.debug("PromptService initialized with store=%s", type(self._store).__name__)

    def load(self) -> None:
        """Load the system prompt for this runtime."""
        logger.info("Loading system prompt for runtime")
        self._prompt = self._store.load()
        logger.debug("Loaded system prompt length=%d", len(self._prompt))

    def get_resolved_prompt_text(self) -> str:
        """Return the resolved system prompt text.

        Returns:
            The current system prompt text.
        """
        return self._prompt

    def get(self) -> str:
        """Return the resolved system prompt.

        Returns:
            The current system prompt text.
        """
        return self.get_resolved_prompt_text()

    def reload(self) -> None:
        """Reload the system prompt from disk."""
        logger.info("Reloading system prompt from disk")
        self._prompt = self._store.reload()
