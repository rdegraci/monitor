"""Response client helpers for Monitor OOP LLM flows."""
from __future__ import annotations

import logging
from typing import Any

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.llm_adapter import ResponsesOpenAiAdapter
from monitor_oop.core.infrastructure.rate_limit_service import RateLimitService
from monitor_oop.core.infrastructure.request_capacity_service import RequestCapacityService
from monitor_oop.core.tools.tool_service import ToolService

logger = logging.getLogger(__name__)


class LLMResponseClient:
    """Create Responses-via-LiteLLM completions for the current runtime."""

    def __init__(
        self,
        config_service: ConfigService,
        adapter: ResponsesOpenAiAdapter,
        tool_service: ToolService | None = None,
        request_capacity_service: RequestCapacityService | None = None,
        rate_limit_service: RateLimitService | None = None,
    ) -> None:
        """Initialize the response client.

        Args:
            config_service: Runtime configuration access.
            adapter: Responses LiteLLM adapter used to create completions.
            tool_service: Optional tool service for response tool schemas.
            request_capacity_service: Optional request capacity service for preflight checks.
            rate_limit_service: Optional rate limit service for preflight checks.
        """

        self.config_service = config_service
        self._adapter = adapter
        self._tool_service = tool_service
        self._request_capacity_service = request_capacity_service
        self._rate_limit_service = rate_limit_service

    def _build_litellm_tools(self) -> list[dict[str, Any]]:
        """Return the current flat Responses-style tool schemas for the adapter."""

        if self._tool_service is None:
            logger.info("Building LiteLLM tools: tool_service unavailable; tool count=0.")
            return []
        tools = self._tool_service.build_responses_tools()
        tool_names = [str(tool.get("name", "<unknown>")) for tool in tools]
        logger.info("Building LiteLLM tools: tool count=%s, tool names=%s.", len(tools), tool_names)
        return tools

    def create_response(self, input_messages: list[dict[str, str]], previous_response_id: str | None = None) -> Any:
        """Create a response using the adapter completion API.

        Args:
            input_messages: The request payload to send to the model.
            previous_response_id: The previous model response identifier, if any.

        Returns:
            The provider response object.
        """

        api_key = self.config_service.get_openai_api_key()
        api_key_present = bool(api_key)
        if not api_key_present:
            logger.error(
                "Cannot create response: OpenAI API key is missing; api_key_present=%s, message_count=%s, previous_response_id=%s.",
                api_key_present,
                len(input_messages),
                previous_response_id,
            )
            raise ValueError("OpenAI API key is required to create a response.")
        api_model_name = self.config_service.get_api_model_name()
        full_model_name = self.config_service.get_full_model_name()
        if not full_model_name:
            logger.error(
                "Cannot create response: full model name is missing; api_key_present=%s, api_model_name=%s, message_count=%s, previous_response_id=%s.",
                api_key_present,
                api_model_name,
                len(input_messages),
                previous_response_id,
            )
            raise ValueError("Full model name is required to create a response.")
        tools = self._build_litellm_tools()
        tool_choice = "auto"
        tool_names = [str(tool.get("name", "<unknown>")) for tool in tools]
        logger.info(
            "Create response model context: full_model_name=%s, api_model_name=%s.",
            full_model_name,
            api_model_name,
        )
        if self._request_capacity_service is not None:
            logger.info(
                "Performing request capacity preflight check: full_model_name=%s, api_model_name=%s, api_key_present=%s, message_count=%s, tool_count=%s, tool_names=%s, previous_response_id=%s.",
                full_model_name,
                api_model_name,
                api_key_present,
                len(input_messages),
                len(tools),
                tool_names,
                previous_response_id,
            )
            request_fits = self._request_capacity_service.request_fits(
                model=full_model_name,
                input_messages=input_messages,
                tools=tools,
                previous_response_id=previous_response_id,
            )
            if request_fits:
                logger.info(
                    "Request capacity preflight check passed: full_model_name=%s, api_model_name=%s, message_count=%s, tool_count=%s, previous_response_id=%s.",
                    full_model_name,
                    api_model_name,
                    len(input_messages),
                    len(tools),
                    previous_response_id,
                )
            else:
                rejection_reason = getattr(self._request_capacity_service, "last_rejection_reason", None)
                if rejection_reason is None:
                    rejection_reason = getattr(self._request_capacity_service, "rejection_reason", None)
                logger.error(
                    "Request capacity preflight check failed: full_model_name=%s, api_model_name=%s, api_key_present=%s, message_count=%s, tool_count=%s, previous_response_id=%s, rejection_reason=%s.",
                    full_model_name,
                    api_model_name,
                    api_key_present,
                    len(input_messages),
                    len(tools),
                    previous_response_id,
                    rejection_reason,
                )
                raise ValueError("Request does not fit within the configured request capacity limits.")
        if self._rate_limit_service is not None:
            logger.info(
                "Performing rate limit preflight check: full_model_name=%s, api_model_name=%s, api_key_present=%s, message_count=%s, tool_count=%s, previous_response_id=%s.",
                full_model_name,
                api_model_name,
                api_key_present,
                len(input_messages),
                len(tools),
                previous_response_id,
            )
            estimated_tokens = self._rate_limit_service.estimate_token_usage(
                model=full_model_name,
                messages=input_messages,
                tools=tools,
                previous_response_id=previous_response_id,
            )
            logger.info(
                "Rate limit preflight check estimated token usage: full_model_name=%s, api_model_name=%s, estimated_tokens=%s, previous_response_id=%s.",
                full_model_name,
                api_model_name,
                estimated_tokens,
                previous_response_id,
            )
            rate_limit_allows = self._rate_limit_service.request_allowed(
                model=full_model_name,
                estimated_tokens=estimated_tokens,
            )
            if rate_limit_allows:
                logger.info(
                    "Rate limit preflight check passed: full_model_name=%s, api_model_name=%s, estimated_tokens=%s, previous_response_id=%s.",
                    full_model_name,
                    api_model_name,
                    estimated_tokens,
                    previous_response_id,
                )
            else:
                logger.warning(
                    "Rate limit preflight check failed: full_model_name=%s, api_model_name=%s, estimated_tokens=%s, api_key_present=%s, previous_response_id=%s.",
                    full_model_name,
                    api_model_name,
                    estimated_tokens,
                    api_key_present,
                    previous_response_id,
                )
                raise ValueError("Request is not allowed by the current rate limit policy.")
        logger.info(
            "Creating response with full_model_name=%s, api_model_name=%s, tool_count=%s, tool_names=%s, tool_choice=%s, message_count=%s, previous_response_id=%s.",
            full_model_name,
            api_model_name,
            len(tools),
            tool_names,
            tool_choice,
            len(input_messages),
            previous_response_id,
        )
        logger.info(
            "Calling adapter.complete with api_model_name=%s and full_model_name context=%s, previous_response_id=%s.",
            api_model_name,
            full_model_name,
            previous_response_id,
        )
        return self._adapter.complete(
            api_model_name,
            input_messages,
            api_key=api_key,
            tools=tools,
            tool_choice=tool_choice,
            previous_response_id=previous_response_id,
        )
