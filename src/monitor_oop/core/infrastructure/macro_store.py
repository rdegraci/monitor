"""Persistent macro storage for Monitor OOP."""
from __future__ import annotations

import logging
from pathlib import Path

import appdirs
import json


logger = logging.getLogger(__name__)


class MacroStore:
    """Load and save macro definitions for one runtime instance."""

    def __init__(self, app_name: str = "monitor") -> None:
        """Initialize the macro store.

        Args:
            app_name: Application name used to resolve the user config directory.
        """

        self._app_name = app_name

    def load(self) -> dict[str, str]:
        """Load macro definitions from disk.

        Returns:
            A mapping of macro names to macro bodies.
        """

        macro_path = self._get_macro_file_path()
        logger.info("Loading macros from %s", macro_path)
        if not macro_path.exists():
            logger.info("Macro file missing at %s; seeding defaults", macro_path)
            self._seed_macro_file(macro_path)
        if not macro_path.exists():
            logger.debug("Macro file still missing at %s after seed attempt", macro_path)
            return {}

        try:
            raw_data = macro_path.read_text(encoding="utf-8")
            data = json.loads(raw_data)
        except OSError:
            logger.error("Failed to read macro file at %s", macro_path, exc_info=True)
            return {}
        except json.JSONDecodeError:
            logger.error("Malformed JSON in macro file at %s", macro_path, exc_info=True)
            return {}

        if not isinstance(data, dict):
            logger.error("Macro file at %s did not contain a JSON object", macro_path)
            return {}

        macros: dict[str, str] = {}
        for key, value in data.items():
            if isinstance(key, str) and isinstance(value, str):
                macros[key] = value
        logger.debug("Loaded %d macros from %s", len(macros), macro_path)
        return macros

    def save(self, macros: dict[str, str]) -> None:
        """Persist macro definitions to disk.

        Args:
            macros: Macro definitions to store.
        """

        macro_path = self._get_macro_file_path()
        logger.info("Saving %d macros to %s", len(macros), macro_path)
        macro_path.parent.mkdir(parents=True, exist_ok=True)
        macro_path.write_text(
            json.dumps(macros, indent=4, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _seed_macro_file(self, macro_path: Path) -> None:
        """Seed the user macro file from the packaged example if available."""

        example_path = Path(__file__).with_name("macros.json.example")
        if not example_path.exists():
            logger.debug("Example macro file missing at %s", example_path)
            return

        logger.info("Seeding macro file at %s from %s", macro_path, example_path)
        try:
            raw_data = example_path.read_text(encoding="utf-8")
            data = json.loads(raw_data)
        except OSError:
            logger.error("Failed to read example macro file at %s", example_path, exc_info=True)
            return
        except json.JSONDecodeError:
            logger.error("Malformed JSON in example macro file at %s", example_path, exc_info=True)
            return

        if not isinstance(data, dict):
            logger.error("Example macro file at %s did not contain a JSON object", example_path)
            return

        macros: dict[str, str] = {}
        for key, value in data.items():
            if isinstance(key, str) and isinstance(value, str):
                macros[key] = value

        if not macros:
            logger.debug("No valid macros found in example macro file at %s", example_path)
            return

        macro_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            macro_path.write_text(
                json.dumps(macros, indent=4, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            logger.debug("Seeded macro file at %s with %d macros", macro_path, len(macros))
        except OSError:
            logger.error("Failed to write seeded macro file at %s", macro_path, exc_info=True)
            return

    def _get_macro_file_path(self) -> Path:
        """Return the user macro file path.

        Returns:
            The resolved macro file path.
        """

        return Path(appdirs.user_config_dir(self._app_name)) / "macros.json"
