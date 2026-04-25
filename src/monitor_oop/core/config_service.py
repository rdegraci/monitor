"""Isolated configuration service for Monitor OOP."""
from __future__ import annotations

from .models import RuntimeConfig


class ConfigService:
    """Owns runtime configuration for a single application instance."""

    def __init__(self, initial_config: RuntimeConfig | None = None) -> None:
        self._config = initial_config or RuntimeConfig()

    def load(self) -> None:
        """Load configuration for the current process."""

        return None

    def reset(self, force: bool = False) -> None:
        """Reset configuration to defaults."""

        self._config = RuntimeConfig()

    def select_model(self, model_name: str) -> bool:
        """Select the active model for this runtime."""

        if model_name:
            self._config.model_name = model_name
            return True
        return False

    def get_model(self) -> str:
        """Return the active model name."""

        return self._config.model_name

    def get_context_window(self) -> int:
        """Return the active context window size."""

        return self._config.context_window
