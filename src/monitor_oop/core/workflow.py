"""Workflow helpers for the isolated Monitor application."""
from __future__ import annotations

from typing import TYPE_CHECKING

from monitor_oop.core.conversation_session import ConversationSession

if TYPE_CHECKING:
    from monitor_oop.core.app import MonitorApp


def process_user_input(session: ConversationSession, text: str) -> bool:
    """Process user input through the provided session."""

    return session.process_user_input(text)


def run_cli(app: MonitorApp) -> int:
    """Run the CLI workflow for the application.

    Returns:
        The exit status for the workflow.
    """

    session = app.context.create_session()
    exit_code = session.start()

    while True:
        try:
            user_input = session.read_user_input()
        except (EOFError, KeyboardInterrupt):
            break
        if session.process_user_input(user_input) is None:
            break

    return exit_code


def run_server(app: MonitorApp) -> int:
    """Run the server workflow for the application."""

    if app.context.server_app is None:
        return 1
    return app.context.server_app.run(host="127.0.0.1", port=5000)


def reset_config(app: MonitorApp, force: bool = False) -> None:
    """Reset runtime configuration through the application."""

    app.context.config_service.reset(force=force)


def run_script(app: MonitorApp, script_path: str) -> int:
    """Run a script workflow for the application."""

    _ = script_path
    return run_cli(app)
