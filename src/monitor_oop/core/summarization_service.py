"""Summarization service for LLM-assisted compaction summaries."""
from __future__ import annotations

from collections.abc import Sequence

from monitor_oop.core.application.llm_request_builder import LLMRequestBuilder
from monitor_oop.core.infrastructure.llm_response_client import LLMResponseClient
from monitor_oop.core.llm_adapter import ResponsesOpenAiAdapter
from monitor_oop.core.models import Message


class SummarizationService:
    """Build LLM-assisted summary text for compacted conversation history."""

    def __init__(
        self,
        config_service,
        request_builder: LLMRequestBuilder,
        response_client: LLMResponseClient,
        response_adapter: ResponsesOpenAiAdapter,
    ) -> None:
        """Create a summarization service.

        Args:
            config_service: Service that provides compaction configuration.
            request_builder: Builder used to construct the summarization request.
            response_client: Client used to execute the summarization request.
            response_adapter: Adapter used to extract assistant text from responses.
        """
        self._config_service = config_service
        self._request_builder = request_builder
        self._response_client = response_client
        self._response_adapter = response_adapter

    def summarize(self, messages: Sequence[Message]) -> str:
        """Build and submit an LLM-assisted summary prompt for the provided history.

        Args:
            messages: The conversation messages being summarized.

        Returns:
            The summary returned by the configured LLM-backed client.
        """
        compaction_config = self._config_service.compaction_config
        message_history = "\n".join(message.content for message in messages)
        prompt = compaction_config.prompt_template.format(
            message_count=len(messages),
            messages=message_history,
        )
        request = self._request_builder.build_summarization_input(
            prompt_text=prompt,
            message_history=messages,
            token_limit=compaction_config.token_limit,
        )
        response = self._response_client.create_response(request)
        return self._response_adapter.extract_text(response)
