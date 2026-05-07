"""Module entry point for the isolated Monitor OOP application."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import TextIO

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

    app = build_app()
    if args.tui:
        return app.run_tui(input_fn=input_fn, output_fn=output_fn)

    status = app.run()
    if status != 0:
        print(
            "OpenAI API key is missing. Set OPENAI_API_KEY and try again.",
            file=sys.stderr,
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
