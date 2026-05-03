"""Persistent system prompt storage for Monitor OOP."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from monitor_oop.core.config_service import ConfigService

logger = logging.getLogger(__name__)


class PromptStore:
    """Load and seed the system prompt for one runtime instance."""

    def __init__(self, config_service: ConfigService) -> None:
        """Initialize the prompt store.

        Args:
            config_service: Configuration service used to resolve the user system prompt file path.
        """
        self._config_service = config_service

    def load(self) -> str:
        """Load the system prompt from disk, seeding it if needed.

        Returns:
            The resolved system prompt text.
        """
        prompt_path = self._get_prompt_file_path()
        logger.info("Loading system prompt from %s", prompt_path)
        if not prompt_path.exists():
            logger.info("System prompt missing at %s; seeding defaults", prompt_path)
            self.seed_from_example()
        if not prompt_path.exists():
            logger.warning("System prompt still missing at %s after seed attempt", prompt_path)
            return ""
        try:
            return prompt_path.read_text(encoding="utf-8")
        except OSError:
            logger.error("Failed to read system prompt at %s", prompt_path, exc_info=True)
            return ""

    def reload(self) -> str:
        """Reload the system prompt from disk.

        Returns:
            The resolved system prompt text.
        """
        return self.load()

    def save(self, prompt_text: str) -> None:
        """Persist the system prompt to disk.

        Args:
            prompt_text: Prompt text to persist.
        """
        prompt_path = self._get_prompt_file_path()
        logger.info("Saving system prompt to %s", prompt_path)
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt_text, encoding="utf-8")

    def seed_from_example(self) -> None:
        """Seed the user prompt file from the packaged example if available."""
        prompt_path = self._get_prompt_file_path()
        example_path = self._get_example_path()
        if not example_path.exists():
            logger.warning("System prompt example missing at %s", example_path)
            return
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(example_path, prompt_path)
            logger.info("Seeded system prompt at %s from %s", prompt_path, example_path)
        except OSError:
            logger.error("Failed to seed system prompt from %s", example_path, exc_info=True)

    def _get_prompt_file_path(self) -> Path:
        """Return the user system prompt file path resolved by configuration service.

        Returns:
            The resolved prompt file path from configuration service.
        """
        return Path(self._config_service.get_system_prompt_file_path())

    def _get_example_path(self) -> Path:
        """Return the packaged example prompt path.

        Returns:
            The resolved example prompt file path.
        """
        return Path(__file__).with_name("system_prompt.example")
