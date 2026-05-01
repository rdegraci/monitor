"""Tests for the isolated Monitor OOP models."""
from monitor_oop.core.models import AppMode, AppState, CommandResult, CommandType, DEFAULT_MODEL, Message, RuntimeConfig


def test_models_default_values() -> None:
    """Verify the shared model defaults."""

    config = RuntimeConfig()
    state = AppState()
    message = Message(role="user", content="hello")
    result = CommandResult(command_type=CommandType.UNKNOWN)

    assert config.model_name == DEFAULT_MODEL
    assert config.context_window == 400_000
    assert state.mode is AppMode.CLI
    assert state.running is False
    assert message.role == "user"
    assert message.content == "hello"
    assert result.command_type is CommandType.UNKNOWN
    assert result.handled is False
    assert result.message == ""
