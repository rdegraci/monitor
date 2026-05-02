"""Response client helpers for Monitor OOP LLM flows."""
from __future__ import annotations

import logging
from typing import Any

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.llm_adapter import ResponsesLiteLLMAdapter
from monitor_oop.core.tools.tool_service import ToolService

logger = logging.getLogger(__name__)


class LLMResponseClient:
    """Create Responses-via-LiteLLM completions for the current runtime."""

    def __init__(
        self,
        config_service: ConfigService,
        tool_service: ToolService | None = None,
        adapter: ResponsesLiteLLMAdapter | None = None,
    ) -> None:
        """Initialize the response client.

        Args:
            config_service: Runtime configuration access.
            tool_service: Optional tool service for response tool schemas.
            adapter: Optional adapter override for testing.
        """

        self.config_service = config_service
        self._tool_service = tool_service
        self.adapter = adapter or ResponsesLiteLLMAdapter()

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
        if not api_key:
            raise ValueError("OpenAI API key is required to create a response.")
        model = self.config_service.get_model()
        if "/" in model:
            model = model.split("/", 1)[1]
        tools = self._build_litellm_tools()
        tool_choice = "auto"
        tool_names = [str(tool.get("name", "<unknown>")) for tool in tools]
        logger.info(
            "Creating response with model=%s, tool_count=%s, tool_names=%s, tool_choice=%s, message_count=%s, previous_response_id=%s.",
            model,
            len(tools),
            tool_names,
            tool_choice,
            len(input_messages),
            previous_response_id,
        )
        return self.adapter.complete(
            model,
            input_messages,
            api_key=api_key,
            tools=tools,
            tool_choice=tool_choice,
            previous_response_id=previous_response_id,
        )
