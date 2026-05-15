"""Turn-scoped tool envelope state for Monitor OOP."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ToolOutputEnvelope:
    """Represent one executed tool call and its response linkage."""

    call_id: str
    response_id: str | None
    response_item_id: str | None
    parent_response_id: str | None
    tool_result: Any


class ToolTurnState:
    """Track per-turn tool output envelopes for LLM orchestration."""

    def __init__(self) -> None:
        """Initialize an empty turn state."""

        self._tool_output_envelopes: list[ToolOutputEnvelope] = []

    def begin_turn(self) -> None:
        """Start a fresh turn by clearing any leftover envelopes."""

        self._tool_output_envelopes.clear()

    def record_envelope(
        self,
        call_id: str,
        response_id: str | None,
        response_item_id: str | None,
        parent_response_id: str | None,
        tool_result: Any,
    ) -> None:
        """Record one tool output envelope for the active turn.

        Args:
            call_id: The tool call identifier.
            response_id: The response identifier for the tool output.
            response_item_id: The response item identifier for the tool output.
            parent_response_id: The parent response identifier for the tool output.
            tool_result: The tool result payload.
        """

        self._tool_output_envelopes.append(
            ToolOutputEnvelope(
                call_id=call_id,
                response_id=response_id,
                response_item_id=response_item_id,
                parent_response_id=parent_response_id,
                tool_result=tool_result,
            )
        )

    def build_follow_up_entries(self) -> list[tuple[str, str | None, Any]]:
        """Return the active turn's envelopes as follow-up payload entries."""

        return [
            (envelope.call_id, envelope.response_item_id, envelope.tool_result)
            for envelope in self._tool_output_envelopes
        ]

    def pending_count(self) -> int:
        """Return the number of pending envelopes in the current turn."""

        return len(self._tool_output_envelopes)

    def clear(self) -> None:
        """Clear all envelopes from the current turn."""

        self._tool_output_envelopes.clear()
