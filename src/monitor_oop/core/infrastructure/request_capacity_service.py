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

        context_window, output_window = self._resolve_capacity_values()
        token_estimate = self._resolve_input_token_estimate(
            input_messages=input_messages,
            tools=tools,
            previous_response_id=previous_response_id,
            estimated_input_tokens=estimated_input_tokens,
        )
        completion_headroom = self._compute_completion_headroom(token_estimate, output_window)
        logger.info(
            "Evaluating request capacity for model=%s, message_count=%s, resolved_context_window=%s, resolved_output_window=%s, estimated_input_tokens=%s, completion_headroom=%s.",
            model,
            len(input_messages),
            context_window,
            output_window,
            token_estimate,
            completion_headroom,
        )
        return self._build_capacity_check_result(
            model=model,
            token_estimate=token_estimate,
            context_window=context_window,
            output_window=output_window,
            completion_headroom=completion_headroom,
        )

    def _resolve_capacity_values(self) -> tuple[int, int]:
        """Resolve and validate capacity configuration values.

        Returns:
            A tuple containing the resolved context window and output window.

        Raises:
            ValueError: If the configured capacity values are invalid.
        """

        try:
            context_window = int(self._config_service.get_context_window())
            output_window = int(self._config_service.get_output_window())
        except (TypeError, ValueError) as exc:
            logger.error(
                "Invalid capacity configuration values returned by config service.",
                exc_info=True,
            )
            raise ValueError("Invalid capacity configuration values returned by config service.") from exc
        if context_window <= 0 or output_window < 0:
            logger.error(
                "Invalid capacity configuration values: context_window=%s, output_window=%s.",
                context_window,
                output_window,
            )
            raise ValueError(
                f"Invalid capacity configuration values: context_window={context_window}, output_window={output_window}."
            )
        return context_window, output_window

    def _resolve_input_token_estimate(
        self,
        input_messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None,
        previous_response_id: str | None,
        estimated_input_tokens: int | None,
    ) -> int:
        """Resolve the input token estimate for a request."""

        if estimated_input_tokens is None:
            return self._estimate_input_tokens(
                input_messages=input_messages,
                tools=tools,
                previous_response_id=previous_response_id,
            )
        return estimated_input_tokens

    def _estimate_input_tokens(
        self,
        input_messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None,
        previous_response_id: str | None,
    ) -> int:
        """Estimate the input token count for a request.

        Delegates to ``ConfigService.estimate_token_usage`` — the canonical
        estimator that the rate-limit preflight also uses — so the two
        preflights evaluate identical numbers.

        Args:
            input_messages: The request payload being evaluated.
            tools: Tool definitions associated with the request.
            previous_response_id: Identifier for a previous response in the chain.

        Returns:
            An estimated token count for the request payload.
        """

        estimate = self._config_service.estimate_token_usage(
            model="",
            messages=input_messages,
            tools=tools,
            previous_response_id=previous_response_id,
        )
        logger.info(
            "Computed input token estimate via canonical estimator: message_count=%s, tool_count=%s, previous_response_id=%s, estimated_input_tokens=%s.",
            len(input_messages),
            0 if tools is None else len(tools),
            previous_response_id,
            estimate,
        )
        return int(estimate)

    def _compute_completion_headroom(self, estimated_input_tokens: int, output_window: int) -> int:
        """Compute reserved completion headroom for a request."""

        reserve_floor = max(16, output_window // 64)
        reserve_factor = max(estimated_input_tokens // 8, 0)
        return min(output_window, max(reserve_floor, reserve_factor))

    def _build_capacity_check_result(
        self,
        model: str,
        token_estimate: int,
        context_window: int,
        output_window: int,
        completion_headroom: int,
    ) -> CapacityCheckResult:
        """Build the final capacity decision result."""

        if token_estimate > context_window:
            reason = (
                f"Request exceeds context window: estimated_input_tokens={token_estimate}, "
                f"context_window={context_window}, completion_headroom={completion_headroom}"
            )
            logger.warning(reason)
            return CapacityCheckResult(
                fits=False,
                estimated_input_tokens=token_estimate,
                context_window=context_window,
                output_window=output_window,
                completion_headroom=completion_headroom,
                reason=reason,
            )
        if completion_headroom > 0 and token_estimate + completion_headroom > context_window:
            reason = (
                f"Request exceeds context window after reserving completion headroom: "
                f"estimated_input_tokens={token_estimate}, context_window={context_window}, "
                f"completion_headroom={completion_headroom}"
            )
            logger.warning(reason)
            return CapacityCheckResult(
                fits=False,
                estimated_input_tokens=token_estimate,
                context_window=context_window,
                output_window=output_window,
                completion_headroom=completion_headroom,
                reason=reason,
            )
        logger.info(
            "Request fits for model=%s: resolved_context_window=%s, resolved_output_window=%s, estimated_input_tokens=%s, completion_headroom=%s.",
            model,
            context_window,
            output_window,
            token_estimate,
            completion_headroom,
        )
        return CapacityCheckResult(
            fits=True,
            estimated_input_tokens=token_estimate,
            context_window=context_window,
            output_window=output_window,
            completion_headroom=completion_headroom,
        )
