"""Summarization service for LLM-assisted compaction summaries."""
from __future__ import annotations

import logging
from collections.abc import Sequence

from monitor_oop.core.application.llm_request_builder import LLMRequestBuilder
from monitor_oop.core.infrastructure.llm_response_client import LLMResponseClient
from monitor_oop.core.llm_adapter import ResponsesOpenAiAdapter
from monitor_oop.core.models import Message

logger = logging.getLogger(__name__)


class SummarizationService:
    """Build LLM-assisted summary text for compacted conversation history."""

    def __init__(
        self,
        config_service,
        request_builder: LLMRequestBuilder,
        response_client: LLMResponseClient,
        response_adapter: ResponsesOpenAiAdapter,
        summarization_prompt_template: str | None = None,
    ) -> None:
        """Create a summarization service.

        Args:
            config_service: Service that provides compaction configuration.
            request_builder: Builder used to construct the summarization request.
            response_client: Client used to execute the summarization request.
            response_adapter: Adapter used to extract assistant text from responses.
            summarization_prompt_template: Template used to build the summary prompt.
                Falls back to config_service.get_summarization_prompt_template() when
                not provided, or to an empty string if that lookup is unavailable.
        """
        self._config_service = config_service
        self._request_builder = request_builder
        self._response_client = response_client
        self._response_adapter = response_adapter
        if summarization_prompt_template is None:
            get_prompt_template = getattr(
                self._config_service,
                "get_summarization_prompt_template",
                None,
            )
            if callable(get_prompt_template):
                summarization_prompt_template = get_prompt_template()
            else:
                summarization_prompt_template = ""
        self._summarization_prompt_template = summarization_prompt_template

    def _get_token_limit(self) -> int | None:
        """Return the summarization token limit from the config service if available.

        Returns:
            The configured token limit, or ``None`` when no supported configuration
            source is available.
        """
        compaction_config = getattr(self._config_service, "compaction_config", None)
        if compaction_config is not None:
            return compaction_config.token_limit
        get_token_limit = getattr(
            self._config_service,
            "get_summarization_token_limit",
            None,
        )
        if callable(get_token_limit):
            return get_token_limit()
        return None

    def summarize(self, messages: Sequence[Message]) -> str:
        """Build and submit an LLM-assisted summary prompt for the provided history.

        Args:
            messages: The conversation messages being summarized.

        Returns:
            The summary returned by the configured LLM-backed client.
        """
        message_count = len(messages)
        token_limit = self._get_token_limit()
        logger.info(
            "Summarizing %s messages with token limit %s",
            message_count,
            token_limit,
        )
        message_history = "\n".join(message.content for message in messages)
        prompt = self._summarization_prompt_template.format(
            message_count=message_count,
            messages=message_history,
        )
        request = self._request_builder.build_summarization_input(
            prompt_text=prompt,
            message_history=messages,
            token_limit=token_limit,
        )
        response = self._response_client.create_response(request)
        return self._response_adapter.extract_text(response)
