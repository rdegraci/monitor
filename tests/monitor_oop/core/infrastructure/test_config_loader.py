"""Tests for ConfigLoader in the Monitor OOP infrastructure layer."""
from __future__ import annotations

from pathlib import Path

import appdirs
import pytest
import yaml

from monitor_oop.core.infrastructure import config_loader as config_loader_module
from monitor_oop.core.infrastructure.config_loader import ConfigLoader
from monitor_oop.core.models import DEFAULT_MODEL


def test_load_config_yaml_defaults_when_no_files_exist(monkeypatch, tmp_path) -> None:
    """Verify YAML loading falls back to defaults when no files exist."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))
    monkeypatch.setattr(ConfigLoader, "_get_user_config_paths", lambda self: [])
    monkeypatch.setattr(ConfigLoader, "_ensure_user_config_yaml", lambda self: None)

    loader = ConfigLoader()
    result = loader.load_config_yaml()

    assert result.model_name == DEFAULT_MODEL
    assert result.context_window == 400_000
    assert result.prompt_history_filename == "prompt_history"
    assert result.history_dir == "history"
    assert result.logging_level == 20


def test_load_config_yaml_creates_example_copy(monkeypatch, tmp_path) -> None:
    """Verify the example config is copied to the user config path on first run."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    example_path = tmp_path / "src" / "monitor_oop" / "core" / "config.yaml.example"
    example_path.parent.mkdir(parents=True)
    example_path.write_text("model: example-model\ncontext_window: 999\nlogging_level: 10\n", encoding="utf-8")

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))
    monkeypatch.setattr(config_loader_module, "__file__", str(tmp_path / "src" / "monitor_oop" / "core" / "config_loader.py"))

    loader = ConfigLoader()
    loader.load_config_yaml()

    config_yaml = config_dir / "config.yaml"
    assert config_yaml.exists()
    assert config_yaml.read_text(encoding="utf-8") == example_path.read_text(encoding="utf-8")


def test_load_config_yaml_reads_runtime_values(monkeypatch, tmp_path) -> None:
    """Verify YAML values are loaded and coerced correctly."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_yaml = config_dir / "config.yaml"
    config_yaml.write_text(
        "model: yaml-model\ncontext_window: 12345\nlogging_level: 30\nprompt_history_filename: custom_history\nhistory_dir: history_dir\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))
    monkeypatch.setattr(ConfigLoader, "_get_user_config_paths", lambda self: [str(config_yaml)])
    monkeypatch.setattr(ConfigLoader, "_ensure_user_config_yaml", lambda self: None)

    loader = ConfigLoader()
    result = loader.load_config_yaml()

    assert result.model_name == "yaml-model"
    assert result.context_window == 12345
    assert result.logging_level == 30
    assert result.prompt_history_filename == "custom_history"
    assert result.history_dir == "history_dir"


def test_load_config_yaml_prefers_last_valid_user_path(monkeypatch, tmp_path) -> None:
    """Verify later user config paths override earlier ones when both exist."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    first_yaml = config_dir / "config.yaml"
    first_yaml.write_text("model: first\n", encoding="utf-8")

    fallback_yaml = tmp_path / ".config" / "monitor" / "config.yaml"
    fallback_yaml.parent.mkdir(parents=True)
    fallback_yaml.write_text("model: second\n", encoding="utf-8")

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))

    original_get_user_config_paths = ConfigLoader._get_user_config_paths

    def fake_get_user_config_paths(self):
        return [str(first_yaml), str(fallback_yaml)]

    monkeypatch.setattr(ConfigLoader, "_get_user_config_paths", fake_get_user_config_paths)
    monkeypatch.setattr(config_loader_module.os.path, "exists", lambda path: True)

    loader = ConfigLoader()
    result = loader.load_config_yaml()

    assert result.model_name == "second"

    monkeypatch.setattr(ConfigLoader, "_get_user_config_paths", original_get_user_config_paths)
