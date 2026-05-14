"""Module entry point for the isolated Monitor OOP application."""
from __future__ import annotations

import argparse
from collections.abc import Callable

from monitor_oop.core.app import build_app


def main(
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], None] | None = None,
) -> int:
    """Run the isolated Monitor OOP application with injectable I/O helpers."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Run the application in TUI mode.",
    )
    args = parser.parse_args()

    if args.tui:
        app = build_app(quiet_bootstrap=True)
        return app.run_tui()

    app = build_app()

    status = app.run()
    return status


if __name__ == "__main__":
    raise SystemExit(main())
