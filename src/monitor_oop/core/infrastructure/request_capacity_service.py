"""Request capacity helpers for Monitor OOP LLM flows."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from monitor_oop.core.config_service import ConfigService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapacityCheckResult:
    """Represent the outcome of a request capacity check."""

    fits: bool
    estimated_input_tokens: int
    context_window: int
    output_window: int
    completion_headroom: int
    reason: str | None = None


class RequestCapacityService:
    """Evaluate whether an LLM request fits the configured model capacity.

    Args:
        config_service: Required runtime configuration access.
    """

    def __init__(self, config_service: ConfigService) -> None:
        """Initialize the request capacity service.

        Args:
            config_service: Required runtime configuration access.
        """

        self._config_service = config_service

    def request_fits(
        self,
        model: str,
        input_messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        previous_response_id: str | None = None,
        estimated_input_tokens: int | None = None,
    ) -> bool:
        """Check whether a request fits the configured model capacity.

        Args:
            model: The model name being requested.
            input_messages: The request payload being evaluated.
            tools: Tool definitions associated with the request.
            previous_response_id: Identifier for a previous response in the chain.
            estimated_input_tokens: Estimated token count for the request payload.

        Returns:
            True if the request fits the available model capacity; otherwise, False.
        """

        result = self.evaluate_request(
            model=model,
            input_messages=input_messages,
            tools=tools,
            previous_response_id=previous_response_id,
            estimated_input_tokens=estimated_input_tokens,
        )
        return result.fits

    def evaluate_request(
        self,
        model: str,
        input_messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        previous_response_id: str | None = None,
        estimated_input_tokens: int | None = None,
    ) -> CapacityCheckResult:
        """Check whether a request fits the model capacity constraints.

        Args:
            model: The model name being requested.
            input_messages: The request payload being evaluated.
            tools: Tool definitions associated with the request.
            previous_response_id: Identifier for a previous response in the chain.
            estimated_input_tokens: Estimated token count for the request payload.

        Returns:
            A structured result describing the capacity decision.
        """

        context_window = int(self._config_service.get_context_window())
        output_window = int(self._config_service.get_output_window())
        estimated_input_tokens = estimated_input_tokens if estimated_input_tokens is not None else self._estimate_input_tokens(
            input_messages=input_messages,
            tools=tools,
            previous_response_id=previous_response_id,
        )
        completion_headroom = self._estimate_completion_headroom(estimated_input_tokens, output_window)
        logger.info(
            "Evaluating request capacity for model=%s, message_count=%s, estimated_input_tokens=%s, context_window=%s, output_window=%s, completion_headroom=%s.",
            model,
            len(input_messages),
            estimated_input_tokens,
            context_window,
            output_window,
            completion_headroom,
        )
        if estimated_input_tokens > context_window:
            reason = (
                f"Request exceeds context window: estimated_input_tokens={estimated_input_tokens}, "
                f"context_window={context_window}, completion_headroom={completion_headroom}"
            )
            logger.warning(reason)
            return CapacityCheckResult(
                fits=False,
                estimated_input_tokens=estimated_input_tokens,
                context_window=context_window,
                output_window=output_window,
                completion_headroom=completion_headroom,
                reason=reason,
            )
        if completion_headroom > 0 and estimated_input_tokens + completion_headroom > context_window:
            reason = (
                f"Request exceeds context window after reserving completion headroom: "
                f"estimated_input_tokens={estimated_input_tokens}, context_window={context_window}, "
                f"completion_headroom={completion_headroom}"
            )
            logger.warning(reason)
            return CapacityCheckResult(
                fits=False,
                estimated_input_tokens=estimated_input_tokens,
                context_window=context_window,
                output_window=output_window,
                completion_headroom=completion_headroom,
                reason=reason,
            )
        return CapacityCheckResult(
            fits=True,
            estimated_input_tokens=estimated_input_tokens,
            context_window=context_window,
            output_window=output_window,
            completion_headroom=completion_headroom,
        )

    def _estimate_input_tokens(
        self,
        input_messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None,
        previous_response_id: str | None,
    ) -> int:
        """Estimate the input token count for a request.

        Args:
            input_messages: The request payload being evaluated.
            tools: Tool definitions associated with the request.
            previous_response_id: Identifier for a previous response in the chain.

        Returns:
            An estimated token count for the request payload.
        """

        estimate = 0
        for message in input_messages:
            content = message.get("content", "")
            estimate += max(1, len(content) // 4)
            estimate += 4
            if message.get("role"):
                estimate += 1
        if tools:
            estimate += sum(max(8, len(str(tool)) // 4) for tool in tools)
        if previous_response_id:
            estimate += max(4, len(previous_response_id) // 4)
        return max(estimate, 1)

    def _estimate_completion_headroom(self, estimated_input_tokens: int, output_window: int) -> int:
        """Estimate reserved completion headroom for a request.

        Args:
            estimated_input_tokens: Estimated token count for the request payload.
            output_window: The model output window.

        Returns:
            The reserved completion headroom in tokens.
        """

        reserve_floor = max(16, output_window // 64)
        reserve_factor = max(estimated_input_tokens // 8, 0)
        return min(output_window, max(reserve_floor, reserve_factor))
