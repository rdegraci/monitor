"""Isolated configuration service for Monitor OOP."""
from __future__ import annotations

import logging
import os

from monitor_oop.core.config_accessor_service import ConfigAccessorService
from monitor_oop.core.config_path_service import ConfigPathContext, ConfigPathService
from monitor_oop.core.config_resolution_service import ConfigResolutionService
from monitor_oop.core.infrastructure.config_loader import ConfigLoader
from monitor_oop.core.infrastructure.env_loader import EnvLoader
from monitor_oop.core.models import DEFAULT_MODEL, RuntimeConfig

logger = logging.getLogger(__name__)


class ConfigService:
    """Owns runtime configuration for a single application instance."""

    def __init__(self, initial_config: RuntimeConfig | None = None) -> None:
        self._config = initial_config or RuntimeConfig(full_model_name=DEFAULT_MODEL)
        self._openai_api_key = os.environ.get("OPENAI_API_KEY")
        self._logging_level = logging.INFO
        self._env_loader = EnvLoader()
        self._config_loader = ConfigLoader()
        self._config_resolution_service = ConfigResolutionService(self._config_loader)
        self._path_context = self._build_path_context(self._config)
        self._path_service = ConfigPathService(self._path_context)
        self._accessor_service = ConfigAccessorService(
            self._config,
            self._openai_api_key,
            self._logging_level,
        )

    def load(self) -> None:
        """Load configuration for the current process."""

        self._load_resolved_configuration()

    def load_env(self) -> None:
        """Load dotenv files and apply environment overrides."""

        self._load_env()
        self._apply_environment_overrides()

    def load_config_yaml(self) -> None:
        """Load YAML configuration using defaults first, then user files."""

        self._load_resolved_configuration()

    def _build_path_context(self, config: RuntimeConfig) -> ConfigPathContext:
        """Build a path context from the current runtime configuration."""

        return ConfigPathContext(
            history_dir=config.history_dir,
            prompt_history_filename=config.prompt_history_filename,
        )

    def _apply_defaults(self) -> None:
        """Reset the runtime configuration to deterministic defaults."""

        self._config = RuntimeConfig(full_model_name=DEFAULT_MODEL)
        logger.info("Applied default runtime configuration: %s", self._config)
        self._logging_level = logging.INFO
        self._openai_api_key = os.environ.get("OPENAI_API_KEY")
        logger.info(
            "OPENAI_API_KEY present in environment during defaults reset: %s",
            self._openai_api_key is not None,
        )
        self._path_context = self._build_path_context(self._config)
        self._path_service = ConfigPathService(self._path_context)
        self._config_loader = ConfigLoader()
        self._config_resolution_service = ConfigResolutionService(self._config_loader)
        self._refresh_accessor_service()

    def _refresh_accessor_service(self) -> None:
        """Rebuild the accessor service from the current runtime state."""

        self._accessor_service = ConfigAccessorService(
            self._config,
            self._openai_api_key,
            self._logging_level,
        )

    def _load_env(self) -> None:
        """Load dotenv files in deterministic precedence order."""

        self._env_loader.load_env()

    def _apply_environment_overrides(self) -> None:
        """Apply environment variable overrides to the resolved configuration."""

        env_values = self._env_loader.apply_environment_overrides(
            self._config,
            current_openai_api_key=self._openai_api_key,
        )
        logger.info(
            "OPENAI_API_KEY present after environment overrides: %s",
            env_values.openai_api_key is not None,
        )
        self._openai_api_key = env_values.openai_api_key
        self._logging_level = env_values.logging_level
        logger.info(
            "Applied environment overrides to runtime configuration: config=%s, openai_api_key=%s, logging_level=%s",
            self._config,
            bool(self._openai_api_key),
            self._logging_level,
        )
        self._refresh_accessor_service()

    def _load_resolved_configuration(self) -> None:
        """Resolve configuration and refresh runtime services."""

        self._apply_defaults()
        resolved_config = self._config_resolution_service.resolve(
            self._config,
        )
        logger.info("Loaded resolved runtime configuration: %s", resolved_config)
        self._apply_resolved_configuration(resolved_config)
        self._load_env()
        self._apply_environment_overrides()

    def _apply_resolved_configuration(
        self,
        resolved_config: RuntimeConfig,
    ) -> None:
        """Apply resolved runtime configuration to local state."""

        self._config = resolved_config
        self._path_context = self._build_path_context(self._config)
        self._path_service = ConfigPathService(self._path_context)
        self._refresh_accessor_service()

    def reset(self) -> None:
        """Reset configuration to defaults."""

        self._load_resolved_configuration()

    def select_model(self, model_name: str) -> bool:
        """Select the active model for this runtime."""

        if not model_name:
            return False

        self._config.full_model_name = model_name
        resolved_config = self._config_resolution_service.resolve(
            self._config,
        )
        self._apply_resolved_configuration(resolved_config)
        return True

    def get_api_model_name(self) -> str:
        """Return the API-facing model name."""

        api_model_name = self._config.api_model_name
        logger.info("Returning api_model_name for adapter: %s", api_model_name)
        return api_model_name

    def get_model(self) -> str:
        """Return the active model name."""

        api_model_name = self.get_api_model_name()
        return api_model_name

    def get_model_alias(self) -> str:
        """Return the alias for the active model name."""

        model_alias = self._accessor_service.get_model_alias()
        return model_alias

    def get_full_model_name(self) -> str:
        """Return the fully resolved model name for the active runtime."""

        full_model_name = self._accessor_service.get_full_model_name()
        logger.info("Returning full model name: %s", full_model_name)
        return full_model_name

    def get_provider(self) -> str:
        """Return the provider prefix for the active model name."""

        provider = self._accessor_service.get_provider()
        logger.info("Returning provider prefix: %s", provider)
        return provider

    def get_tokens_per_minute(self, model_name: str | None = None) -> int:
        """Return the tokens-per-minute limit for a model.

        Args:
            model_name: The optional model name to inspect.

        Returns:
            int: The tokens-per-minute limit for the resolved model.
        """

        tokens_per_minute = self._accessor_service.get_model_tpm_limit(model_name)
        return tokens_per_minute

    def get_requests_per_minute(self, model_name: str | None = None) -> int:
        """Return the requests-per-minute limit for a model.

        Args:
            model_name: The optional model name to inspect.

        Returns:
            int: The requests-per-minute limit for the resolved model.
        """

        requests_per_minute = self._accessor_service.get_model_rpm_limit(model_name)
        return requests_per_minute

    def estimate_token_usage(
        self,
        model: str,
        messages: list[dict[str, object]] | None,
        tools: list[dict[str, object]] | None,
        previous_response_id: str | None,
    ) -> int:
        """Estimate token usage for a request.

        Args:
            model: The model name being used for the request.
            messages: The request messages.
            tools: The request tools.
            previous_response_id: The previous response identifier, if any.

        Returns:
            int: A conservative estimate of token usage for the request.
        """

        return self._accessor_service.estimate_token_usage(
            model,
            messages,
            tools,
            previous_response_id,
        )

    def get_context_window(self) -> int:
        """Return the active context window size."""

        context_window = self._accessor_service.get_context_window()
        logger.info("Returning context window: %s", context_window)
        return context_window

    def get_output_window(self) -> int:
        """Return the active output window size."""

        output_window = self._accessor_service.get_output_window()
        logger.info("Returning output window: %s", output_window)
        return output_window

    def get_summarization_prompt_template(self) -> str:
        """Return the summarization prompt template for the active runtime."""

        return self._accessor_service.get_summarization_prompt_template()

    def get_summarization_token_limit(self) -> int:
        """Return the summarization token limit for the active runtime."""

        return self._accessor_service.get_summarization_token_limit()

    def get_conversation_turn_budget(self) -> int:
        """Return the conversation turn budget for the active runtime."""

        return self._accessor_service.get_conversation_turn_budget()

    def get_model_tpm_limit(self, model_name: str | None = None) -> int:
        """Return the tokens-per-minute limit for a model.

        The requested model name is used when provided; otherwise the current
        runtime model is checked. If no model-specific TPM value is available,
        return a small positive default.
        """

        return self._accessor_service.get_model_tpm_limit(model_name)

    def get_model_rpm_limit(self, model_name: str | None = None) -> int:
        """Return the requests-per-minute limit for a model.

        The requested model name is used when provided; otherwise the current
        runtime model is checked. If no model-specific RPM value is available,
        return 0.
        """

        return self._accessor_service.get_model_rpm_limit(model_name)

    def get_persistent_history_file_path(self) -> str:
        """Return the first writable persistent history file path."""

        return self._path_service.get_persistent_history_file_path()

    def get_system_prompt_file_path(self) -> str:
        """Return the first writable system prompt file path."""

        return self._path_service.get_system_prompt_file_path()

    def get_log_file_path(self) -> str:
        """Return the first writable per-process log file path."""

        return self._path_service.get_log_file_path()

    def get_history_file_path(self) -> str:
        """Return the persistent prompt history file path."""

        return self.get_persistent_history_file_path()

    def get_openai_api_key(self) -> str | None:
        """Return the effective OPENAI_API_KEY for this runtime."""

        openai_api_key = self._accessor_service.get_openai_api_key()
        if openai_api_key is None or not openai_api_key.strip():
            raise ValueError("OPENAI_API_KEY is required and must not be empty.")
        logger.info(
            "Accessor returned OPENAI_API_KEY present=%s length=%s",
            openai_api_key is not None,
            len(openai_api_key) if openai_api_key is not None else 0,
        )
        return openai_api_key

    def get_logging_level(self) -> int:
        """Return the logging level from LOG_LEVEL with a safe INFO default.

        Returns:
            int: The resolved logging level constant.
        """

        logging_level = self._accessor_service.get_logging_level()
        return logging_level
