"""Background turn completion results for the Monitor OOP TUI."""
from __future__ import annotations

from dataclasses import dataclass, field

from monitor_oop.core.models import Message


@dataclass(frozen=True, slots=True)
class TurnCompletionResult:
    """Structured result of completing one background turn for history enrichment.

    Attributes:
        task_id: The task identifier associated with the turn.
        input_text: The submitted user input for the turn.
        assistant_text: The assistant response text produced for the turn.
        success: Whether the turn completed successfully.
        status_text: The status text describing the completed turn outcome.
        response_id: The assistant response identifier produced for the turn, if available.
        parent_response_id: The parent response identifier associated with the turn, if available.
        messages: Structured conversation messages available for history enrichment, including
            richer assistant and tool messages when available.
        failure_kind: When ``success`` is ``False``, a coarse classification of the
            failure used to drive presentation. ``"rate_limited"`` is currently the
            only recognized non-default value and lets the TUI render a distinct
            transient-failure indicator instead of the generic ``"failed (idle)"``.
    """

    task_id: str
    input_text: str
    success: bool
    assistant_text: str = ""
    status_text: str = ""
    response_id: str | None = None
    parent_response_id: str | None = None
    messages: list[Message] = field(default_factory=list)
    failure_kind: str | None = None

    @property
    def has_messages(self) -> bool:
        return bool(self.messages)
