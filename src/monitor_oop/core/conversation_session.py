"""Conversation session handling for the isolated Monitor application."""
from __future__ import annotations

from monitor_oop.core.models import CommandType, Message
from monitor_oop.core.runtime_context import RuntimeContext


class ConversationSession:
    """Owns the interactive session lifecycle for a single runtime."""

    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self.running = False

    def start(self) -> int:
        """Start the session and return an exit code."""

        self.running = True
        self.context.state.running = True
        return 0

    def step(self) -> bool:
        """Run one interactive step."""

        return self.running

    def prompt_user(self) -> str:
        """Return the prompt string for the current session."""

        return "> "

    def handle_model_switch(self) -> None:
        """Handle model switching behavior for the session."""

        return None

    def process_user_input(self, user_input: str) -> bool:
        """Process one user input and update session state."""

        result = self.context.command_processor.process(user_input)
        if result.command_type is CommandType.EXIT:
            self.running = False
            self.context.state.running = False
            return False
        self.context.history_service.append(Message(role="user", content=user_input))
        print("Response pending LLM integration.")
        return True
