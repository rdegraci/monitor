"""Summarization service for LLM-assisted compaction summaries."""
from __future__ import annotations

import logging
from collections.abc import Sequence

from monitor_oop.core.application.llm_request_builder import LLMRequestBuilder
from monitor_oop.core.infrastructure.llm_response_client import LLMResponseClient
from monitor_oop.core.llm_adapter import ResponsesOpenAiAdapter
from monitor_oop.core.models import Message

logger = logging.getLogger(__name__)


_FALLBACK_PRIOR_CHAR_CAP_DEFAULT = 16_000
_FALLBACK_PRIOR_CHARS_PER_TOKEN = 4


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
        """Return the summarization token limit clamped to the model's output window.

        The configured ``token_limit`` is a *target* size for the summary; the
        model can only produce up to ``output_window`` tokens per call. If the
        configured limit exceeds the output window, ``max_output_tokens`` would
        be rejected by the provider and the summarization call would fail —
        leaving the deterministic fallback to overwrite real history with a
        placeholder. Clamping here keeps the cap real.

        Returns:
            The clamped token limit, or ``None`` when no supported configuration
            source is available.
        """
        raw_limit = self._read_raw_token_limit()
        if raw_limit is None:
            return None
        output_window = self._read_output_window()
        if output_window is not None and output_window > 0:
            clamped = min(raw_limit, output_window)
            if clamped != raw_limit:
                logger.info(
                    "Clamped summarization token_limit from %s to output_window=%s",
                    raw_limit,
                    output_window,
                )
            return clamped
        return raw_limit

    def _read_raw_token_limit(self) -> int | None:
        get_token_limit = getattr(
            self._config_service,
            "get_summarization_token_limit",
            None,
        )
        if callable(get_token_limit):
            return get_token_limit()
        return None

    def _read_output_window(self) -> int | None:
        get_output_window = getattr(self._config_service, "get_output_window", None)
        if not callable(get_output_window):
            return None
        try:
            return get_output_window()
        except Exception:
            logger.exception("Failed to read output_window for token_limit clamp")
            return None

    def summarize(self, messages: Sequence[Message]) -> str:
        """Build and submit an LLM-assisted summary prompt for the provided history.

        Falls back to a deterministic placeholder when the LLM call fails or
        returns empty text. The fallback guarantees forward progress for the
        caller (compaction always completes), at the cost of summary fidelity.

        Args:
            messages: The conversation messages being summarized.

        Returns:
            The summary returned by the configured LLM-backed client, or a
            deterministic placeholder on failure.
        """
        message_count = len(messages)
        token_limit = self._get_token_limit()
        logger.info(
            "Summarizing %s messages with token limit %s",
            message_count,
            token_limit,
        )
        prompt = self._summarization_prompt_template.format(
            message_count=message_count,
        )
        request = self._request_builder.build_summarization_input(
            prompt_text=prompt,
            message_history=messages,
        )
        try:
            response = self._response_client.create_response(
                request,
                max_output_tokens=token_limit,
            )
            text = self._response_adapter.extract_text(response)
            if text:
                return text
            logger.warning(
                "Summarization returned empty text; using deterministic fallback"
            )
        except Exception:
            logger.exception(
                "Summarization LLM call failed; using deterministic fallback"
            )
        return self._build_fallback_summary(messages)

    def _build_fallback_summary(self, messages: Sequence[Message]) -> str:
        """Return a deterministic summary used when the LLM call fails.

        Carries forward the prior compaction summary (if any) so transient
        summarization failures don't erase real LLM-derived context. The prior
        summary is truncated from the *end* before the new placeholder line is
        appended, so older high-signal content (the original LLM summary)
        survives longer than newer low-signal placeholder accumulations.
        """

        placeholder = (
            f"[Compacted summary placeholder for {len(messages)} prior messages]"
        )
        prior_summary = self._find_prior_system_summary(messages)
        if not prior_summary:
            return placeholder
        capped_prior = self._cap_prior_summary(prior_summary)
        return f"{capped_prior}\n\n{placeholder}"

    def _find_prior_system_summary(self, messages: Sequence[Message]) -> str | None:
        """Return the content of the leading system summary in ``messages``.

        Compaction always emits exactly one system summary at the head of
        history followed by the preserved tail, so only the first message is
        considered.
        """

        for message in messages:
            if message.role == "system":
                return message.content
            return None
        return None

    def _cap_prior_summary(self, prior_summary: str) -> str:
        """Truncate the prior summary from the end to fit the configured cap."""

        char_cap = self._compute_prior_char_cap()
        if char_cap <= 0 or len(prior_summary) <= char_cap:
            return prior_summary
        truncated = prior_summary[:char_cap]
        return f"{truncated}\n[... summary truncated to fit cap ...]"

    def _compute_prior_char_cap(self) -> int:
        """Return the char-count cap for carrying forward a prior summary."""

        token_limit = self._read_raw_token_limit()
        if token_limit is None or token_limit <= 0:
            return _FALLBACK_PRIOR_CHAR_CAP_DEFAULT
        return token_limit * _FALLBACK_PRIOR_CHARS_PER_TOKEN
