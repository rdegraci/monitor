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

    def _get_user_config_dir(self) -> Path:
        return Path(self._path_service.get_user_config_dir_path())

    def _get_yaml_example_path(self) -> Path:
        return Path(__file__).with_name("config.yaml.example")

    def _get_model_config_example_path(self) -> Path:
        return Path(__file__).resolve().parents[2] / "model_config_v2.json"

    def seed_yaml_config(self) -> Path | None:
        """Seed config.yaml from the packaged example if it is missing."""

        config_dir = self._get_user_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.yaml"
        if config_path.exists():
            logger.info("User YAML config already exists at %s", config_path)
            return None
        example_path = self._get_yaml_example_path()
        if not example_path.exists():
            logger.warning("Packaged YAML example missing at %s", example_path)
            return None
        try:
            shutil.copyfile(example_path, config_path)
            logger.info("Seeded user YAML config at %s from %s", config_path, example_path)
            return config_path
        except OSError:
            logger.error("Failed to seed YAML config from %s", example_path, exc_info=True)
            return None

    def seed_model_config(self) -> Path | None:
        """Seed model_config_v2.json from the packaged example if it is missing."""

        config_dir = self._get_user_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "model_config_v2.json"
        if config_path.exists():
            logger.info("User model config already exists at %s", config_path)
            return None
        example_path = self._get_model_config_example_path()
        if not example_path.exists():
            logger.warning("Packaged model config missing at %s", example_path)
            return None
        try:
            shutil.copyfile(example_path, config_path)
            logger.info("Seeded user model config at %s from %s", config_path, example_path)
            return config_path
        except OSError:
            logger.error("Failed to seed model config from %s", example_path, exc_info=True)
            return None

    def seed_user_config(self) -> list[Path]:
        """Seed all supported user configuration files and return created paths."""

        created_paths: list[Path] = []
        yaml_path = self.seed_yaml_config()
        if yaml_path is not None:
            created_paths.append(yaml_path)
        model_config_path = self.seed_model_config()
        if model_config_path is not None:
            created_paths.append(model_config_path)
        return created_paths

    def seed_all(self) -> None:
        """Seed all supported user configuration files."""

        self.seed_user_config()
