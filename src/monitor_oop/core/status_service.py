"""Status service for Monitor OOP."""
from __future__ import annotations


class StatusService:
    """Owns the current runtime status."""

    def __init__(self, initial_state: str = "idle") -> None:
        self._state = initial_state

    def set_idle(self) -> None:
        """Set the runtime state to idle."""

        self._state = "idle"

    def set_working(self) -> None:
        """Set the runtime state to working."""

        self._state = "working"

    def get_state(self) -> str:
        """Return the current runtime state."""

        return self._state

    def start_server(self) -> str:
        """Mark the status service as active for server mode."""

        self.set_working()
        return self._state

    def stop_server(self) -> None:
        """Stop server mode and return to idle."""

        self.set_idle()
