"""Module entry point for the isolated Monitor OOP application."""
from __future__ import annotations

import argparse
import sys

from monitor_oop.core.app import build_app


def main() -> int:
    """Run the isolated Monitor OOP application."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Run the application in TUI mode.",
    )
    args = parser.parse_args()

    app = build_app()
    if args.tui:
        return app.run_tui()

    status = app.run()
    if status != 0:
        print(
            "OpenAI API key is missing. Set OPENAI_API_KEY and try again.",
            file=sys.stderr,
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
