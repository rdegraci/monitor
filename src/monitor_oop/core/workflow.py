"""Workflow helpers for the isolated Monitor application."""
from __future__ import annotations

from typing import TYPE_CHECKING

from monitor_oop.core.conversation_session import ConversationSession
from monitor_oop.core.infrastructure.rate_limit_service import RateLimitDeniedError

if TYPE_CHECKING:
    from monitor_oop.core.app import MonitorApp


def process_user_input(session: ConversationSession, text: str) -> bool:
    """Process user input through the provided session."""

    return session.process_user_input(text)


def _run_cli_session(session: ConversationSession) -> int:
    exit_code = session.start()

    while True:
        try:
            user_input = session.read_user_input()
        except (EOFError, KeyboardInterrupt):
            break
        try:
            assistant_response = session.process_user_input(user_input)
        except RateLimitDeniedError as denial:
            # Recoverable: rate limit hit. Tell the user what happened (with
            # which limit tripped and approximate retry-after) and keep the
            # REPL loop alive so they can wait and try again.
            print(f"[rate limit] {denial}")
            continue
        if assistant_response is None:
            break
        print(assistant_response)

    return exit_code


def run_cli(app: MonitorApp) -> int:
    """Run the CLI workflow for the application.

    Returns:
        The exit status for the workflow.
    """

    session = app.context.create_session()
    return _run_cli_session(session)


def _run_server_app(app: MonitorApp) -> int:
    if app.context.server_app is None:
        return 1
    return app.context.server_app.run(host="127.0.0.1", port=5000)


def run_server(app: MonitorApp) -> int:
    """Run the server workflow for the application."""

    return _run_server_app(app)


def _reset_runtime_config(app: MonitorApp, force: bool = False) -> None:
    app.context.config_service.reset(force=force)


def reset_config(app: MonitorApp, force: bool = False) -> None:
    """Reset runtime configuration through the application."""

    _reset_runtime_config(app, force=force)


def _run_script_workflow(app: MonitorApp, script_path: str) -> int:
    _ = script_path
    return run_cli(app)


def run_script(app: MonitorApp, script_path: str) -> int:
    """Run a script workflow for the application."""

    return _run_script_workflow(app, script_path)
