"""Module entry point for the isolated Monitor OOP application."""
from __future__ import annotations

from monitor_oop.core.app import build_app


def main() -> int:
    """Run the isolated Monitor OOP application."""

    app = build_app()
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
