"""Response client helpers for Monitor OOP LLM flows."""
from __future__ import annotations

import logging
from typing import Any

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.infrastructure.rate_limit_service import RateLimitService
from monitor_oop.core.infrastructure.request_capacity_service import RequestCapacityService
from monitor_oop.core.llm_adapter import ResponsesOpenAiAdapter
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

    def _get_rate_limit_wait_policy(self) -> dict[str, Any]:
        """Return optional wait policy values for rate limiting.

        The runtime config may expose wait policy attributes on some deployments.
        This helper reads those values conservatively and only returns keys that
        are present and usable.
        """

        wait_policy: dict[str, Any] = {}

        wait_policy_value = getattr(self.config_service, "rate_limit_wait_policy", None)
        if wait_policy_value is not None:
            wait_policy["wait_policy"] = wait_policy_value

        wait_timeout_seconds = getattr(self.config_service, "rate_limit_wait_timeout_seconds", None)
        if wait_timeout_seconds is not None:
            wait_policy["wait_timeout_seconds"] = wait_timeout_seconds

        return wait_policy

    def _get_rate_limit_allow_wait(self) -> bool | None:
        """Return optional allow-wait configuration for rate limiting."""

        allow_wait = getattr(self.config_service, "rate_limit_allow_wait", None)
        if allow_wait is not None:
            return bool(allow_wait)
        return None

    def _validate_required_config(self, input_messages: list[dict[str, str]]) -> tuple[Any, str]:
        """Validate required config values for response creation."""

        api_key = self.config_service.get_openai_api_key()
        api_key_present = bool(api_key)
        if not api_key_present:
            logger.error(
                "Cannot create response: OpenAI API key is missing; api_key_present=%s, message_count=%s, previous_response_id=%s.",
                api_key_present,
                len(input_messages),
                None,
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
                None,
            )
            raise ValueError("Full model name is required to create a response.")
        return api_key, full_model_name

    def _prepare_tool_schema(self) -> tuple[list[dict[str, Any]], list[str]]:
        """Prepare tool schemas and tool names for response creation."""

        tools = self._build_litellm_tools()
        tool_names = [str(tool.get("name", "<unknown>")) for tool in tools]
        return tools, tool_names

    def _run_request_capacity_preflight(
        self,
        full_model_name: str,
        api_model_name: str,
        api_key_present: bool,
        input_messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        tool_names: list[str],
        previous_response_id: str | None,
    ) -> None:
        """Run request capacity preflight checks."""

        if self._request_capacity_service is None:
            return
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
            return
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

    def _run_rate_limit_preflight(
        self,
        full_model_name: str,
        api_model_name: str,
        api_key_present: bool,
        input_messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        previous_response_id: str | None,
    ) -> int | None:
        """Run rate limit preflight checks."""

        if self._rate_limit_service is None:
            return None
        allow_wait = self._get_rate_limit_allow_wait()
        wait_policy_kwargs = self._get_rate_limit_wait_policy()
        if allow_wait is True:
            logger.info(
                "Rate limit preflight configured for wait-enabled behavior: full_model_name=%s, api_model_name=%s, allow_wait=%s, wait_policy=%s, wait_timeout_seconds=%s, previous_response_id=%s.",
                full_model_name,
                api_model_name,
                allow_wait,
                wait_policy_kwargs.get("wait_policy"),
                wait_policy_kwargs.get("wait_timeout_seconds"),
                previous_response_id,
            )
        else:
            logger.info(
                "Rate limit preflight configured for fail-fast behavior: full_model_name=%s, api_model_name=%s, allow_wait=%s, previous_response_id=%s.",
                full_model_name,
                api_model_name,
                allow_wait,
                previous_response_id,
            )
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
        request_allowed_kwargs = {
            "model": full_model_name,
            "estimated_tokens": estimated_tokens,
        }
        if allow_wait is not None:
            request_allowed_kwargs["allow_wait"] = allow_wait
        if "wait_timeout_seconds" in wait_policy_kwargs:
            request_allowed_kwargs["wait_timeout_seconds"] = wait_policy_kwargs["wait_timeout_seconds"]
        logger.info(
            "Calling request_allowed with rate limit context: full_model_name=%s, api_model_name=%s, estimated_tokens=%s, allow_wait=%s, wait_policy=%s, wait_timeout_seconds=%s, previous_response_id=%s.",
            full_model_name,
            api_model_name,
            estimated_tokens,
            request_allowed_kwargs.get("allow_wait"),
            wait_policy_kwargs.get("wait_policy"),
            request_allowed_kwargs.get("wait_timeout_seconds"),
            previous_response_id,
        )
        rate_limit_allows = self._rate_limit_service.request_allowed(**request_allowed_kwargs)
        if rate_limit_allows:
            logger.info(
                "Rate limit preflight check passed: full_model_name=%s, api_model_name=%s, estimated_tokens=%s, allow_wait=%s, previous_response_id=%s.",
                full_model_name,
                api_model_name,
                estimated_tokens,
                allow_wait,
                previous_response_id,
            )
            return estimated_tokens
        logger.warning(
            "Rate limit preflight check failed: full_model_name=%s, api_model_name=%s, estimated_tokens=%s, api_key_present=%s, allow_wait=%s, previous_response_id=%s.",
            full_model_name,
            api_model_name,
            estimated_tokens,
            api_key_present,
            allow_wait,
            previous_response_id,
        )
        raise ValueError("Request is not allowed by the current rate limit policy.")

    def _record_rate_limit_request_usage(
        self,
        full_model_name: str,
        estimated_tokens: int | None,
        previous_response_id: str | None,
        response: Any = None,
    ) -> None:
        """Record successful request usage in the rate limit service.

        Prefers the provider-reported ``response.usage.total_tokens`` when
        available so the rolling budget tracks actual usage rather than the
        preflight estimate. Falls back to the estimate when the response
        carries no usage payload.
        """

        if self._rate_limit_service is None:
            return
        actual_tokens = self._extract_response_total_tokens(response)
        tokens_to_record = actual_tokens if actual_tokens is not None else estimated_tokens
        if tokens_to_record is None:
            return
        logger.info(
            "Recording successful request usage: full_model_name=%s, actual_tokens=%s, estimated_tokens=%s, previous_response_id=%s.",
            full_model_name,
            actual_tokens,
            estimated_tokens,
            previous_response_id,
        )
        self._rate_limit_service.record_request_for_model(
            model=full_model_name, tokens=tokens_to_record
        )
        # Cache this response's total_tokens keyed by its own id so a future
        # request that chains via previous_response_id can include the
        # server-side context in its preflight estimate.
        response_id = self._extract_response_id(response)
        if response_id is not None and actual_tokens is not None:
            cache_method = getattr(
                self._rate_limit_service, "record_response_total_tokens", None
            )
            if callable(cache_method):
                cache_method(response_id, actual_tokens)

    def _extract_response_id(self, response: Any) -> str | None:
        """Return ``response.id`` (attribute or dict form), or ``None``."""

        if response is None:
            return None
        response_id = getattr(response, "id", None)
        if response_id is None and isinstance(response, dict):
            response_id = response.get("id")
        if response_id is None:
            return None
        return str(response_id)

    def _extract_response_total_tokens(self, response: Any) -> int | None:
        """Best-effort extraction of the provider-reported total token usage.

        Supports the OpenAI Responses-style ``usage.total_tokens`` /
        ``input_tokens + output_tokens`` shape and the Chat Completions
        ``prompt_tokens + completion_tokens`` shape. Tolerates both attribute
        and dict-style access. Returns ``None`` when no usage payload can be
        recovered so the caller falls back to the preflight estimate.
        """

        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        if usage is None:
            return None

        def _read(name: str) -> int | None:
            value = getattr(usage, name, None)
            if value is None and isinstance(usage, dict):
                value = usage.get(name)
            if value is None:
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        total = _read("total_tokens")
        if total is not None:
            return total
        input_tokens = _read("input_tokens")
        output_tokens = _read("output_tokens")
        if input_tokens is not None and output_tokens is not None:
            return input_tokens + output_tokens
        prompt = _read("prompt_tokens")
        completion = _read("completion_tokens")
        if prompt is not None and completion is not None:
            return prompt + completion
        return None

    def _invoke_adapter(
        self,
        api_model_name: str,
        input_messages: list[dict[str, str]],
        api_key: str,
        tools: list[dict[str, Any]],
        tool_choice: str,
        previous_response_id: str | None,
        full_model_name: str,
        max_output_tokens: int | None = None,
    ) -> Any:
        """Invoke the completion adapter."""

        logger.info(
            "Calling adapter.complete with api_model_name=%s and full_model_name context=%s, previous_response_id=%s, max_output_tokens=%s.",
            api_model_name,
            full_model_name,
            previous_response_id,
            max_output_tokens,
        )
        adapter_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "tools": tools,
            "tool_choice": tool_choice,
            "previous_response_id": previous_response_id,
        }
        if max_output_tokens is not None:
            adapter_kwargs["max_output_tokens"] = max_output_tokens
        return self._adapter.complete(
            api_model_name,
            input_messages,
            **adapter_kwargs,
        )

    def create_response(
        self,
        input_messages: list[dict[str, str]],
        previous_response_id: str | None = None,
        max_output_tokens: int | None = None,
    ) -> Any:
        """Create a response using the adapter completion API.

        Args:
            input_messages: The request payload to send to the model.
            previous_response_id: The previous model response identifier, if any.
            max_output_tokens: Hard cap on the model's output tokens, when set.

        Returns:
            The provider response object.
        """

        api_key, full_model_name = self._validate_required_config(input_messages)
        api_model_name = self.config_service.get_api_model_name()
        api_key_present = bool(api_key)
        tools, tool_names = self._prepare_tool_schema()
        tool_choice = "auto"
        logger.info(
            "Create response model context: full_model_name=%s, api_model_name=%s.",
            full_model_name,
            api_model_name,
        )
        self._run_request_capacity_preflight(
            full_model_name=full_model_name,
            api_model_name=api_model_name,
            api_key_present=api_key_present,
            input_messages=input_messages,
            tools=tools,
            tool_names=tool_names,
            previous_response_id=previous_response_id,
        )
        estimated_tokens = self._run_rate_limit_preflight(
            full_model_name=full_model_name,
            api_model_name=api_model_name,
            api_key_present=api_key_present,
            input_messages=input_messages,
            tools=tools,
            previous_response_id=previous_response_id,
        )
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
        response = self._invoke_adapter(
            api_model_name=api_model_name,
            input_messages=input_messages,
            api_key=api_key,
            tools=tools,
            tool_choice=tool_choice,
            previous_response_id=previous_response_id,
            full_model_name=full_model_name,
            max_output_tokens=max_output_tokens,
        )
        self._record_rate_limit_request_usage(
            full_model_name=full_model_name,
            estimated_tokens=estimated_tokens,
            previous_response_id=previous_response_id,
            response=response,
        )
        return response
