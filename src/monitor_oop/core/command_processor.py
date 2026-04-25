"""Command processing for the isolated Monitor application."""
from __future__ import annotations

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.models import CommandResult, CommandType
from monitor_oop.core.status_service import StatusService


class CommandProcessor:
    """Classifies and executes commands for one runtime instance."""

    def __init__(
        self,
        config_service: ConfigService,
        history_service: HistoryService,
        macro_service: MacroService,
        status_service: StatusService,
    ) -> None:
        self.config_service = config_service
        self.history_service = history_service
        self.macro_service = macro_service
        self.status_service = status_service

    def evaluate(self, command: str) -> CommandResult:
        """Classify an input command without executing it."""

        normalized = command.strip().lower()
        if normalized in {":quit", ":exit", "exit", "quit"}:
            return CommandResult(command_type=CommandType.EXIT, handled=True, message="Exiting session.")
        if normalized.startswith(":model "):
            return CommandResult(command_type=CommandType.MODEL, handled=True, message=command.strip())
        if normalized.startswith("{{") and normalized.endswith("}}"):
            return CommandResult(command_type=CommandType.MACRO, handled=True, message=command.strip())
        return CommandResult(command_type=CommandType.UNKNOWN, handled=False, message=command.strip())

    def execute(self, result: CommandResult, original_command: str) -> CommandResult:
        """Execute a previously classified command."""

        if result.command_type is CommandType.MODEL:
            model_name = original_command.strip().split(maxsplit=1)[-1]
            if self.config_service.select_model(model_name):
                return CommandResult(command_type=CommandType.MODEL, handled=True, message=f"Model set to {model_name}.")
            return CommandResult(command_type=CommandType.MODEL, handled=False, message="Model selection failed.")
        if result.command_type is CommandType.MACRO:
            expanded = self.macro_service.expand(original_command)
            return CommandResult(command_type=CommandType.MACRO, handled=True, message=expanded)
        return result

    def process(self, command: str) -> CommandResult:
        """Evaluate and execute a command in one step."""

        result = self.evaluate(command)
        return self.execute(result, command)
