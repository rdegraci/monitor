"""Helpers for seeding user configuration files."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from monitor_oop.core.config_path_service import ConfigPathService

logger = logging.getLogger(__name__)


class UserConfigSeeder:
    """Seed user configuration files from packaged examples when needed."""

    def __init__(self, path_service: ConfigPathService) -> None:
        """Initialize the seeder.

        Args:
            path_service: Path service used to resolve the user config directory.
        """

        self._path_service = path_service

    def seed_yaml_config(self) -> None:
        """Seed config.yaml from the packaged example if it is missing."""

        config_dir = Path(self._path_service.get_user_config_dir_path())
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.yaml"
        if config_path.exists():
            logger.info("User YAML config already exists at %s", config_path)
            return
        example_path = Path(__file__).with_name("config.yaml.example")
        if not example_path.exists():
            logger.warning("Packaged YAML example missing at %s", example_path)
            return
        try:
            shutil.copyfile(example_path, config_path)
            logger.info("Seeded user YAML config at %s from %s", config_path, example_path)
        except OSError:
            logger.error("Failed to seed YAML config from %s", example_path, exc_info=True)

    def seed_all(self) -> None:
        """Seed all supported user configuration files."""

        self.seed_yaml_config()
