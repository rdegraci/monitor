"""Background turn completion results for the Monitor OOP TUI."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TurnCompletionResult:
    """Result of completing one background turn.

    Attributes:
        task_id: The task identifier associated with the turn.
        input_text: The submitted user input for the turn.
        assistant_text: The assistant response text produced for the turn.
        success: Whether the turn completed successfully.
        status_text: The status text describing the completed turn outcome.
    """

    task_id: str
    input_text: str
    success: bool
    assistant_text: str = ""
    status_text: str = ""
