"""Tests for ConfigLoader in the Monitor OOP infrastructure layer."""
from __future__ import annotations

from pathlib import Path

from monitor._stubs import appdirs, yaml
import pytest

from monitor_oop.core.infrastructure import config_loader as config_loader_module
from monitor_oop.core.infrastructure.config_loader import ConfigLoader
from monitor_oop.core.models import DEFAULT_MODEL


def test_load_config_yaml_delegates_to_yaml_loader_and_returns_loaded_values(monkeypatch, tmp_path) -> None:
    """Verify the thin wrapper delegates YAML loading and returns loaded config values."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_yaml = config_dir / "config.yaml"
    config_yaml.write_text(
        "model: yaml-model\ncontext_window: 12345\nlogging_level: 30\nprompt_history_filename: custom_history\nhistory_dir: history_dir\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))

    loader = ConfigLoader()
    result = loader.load_config_yaml()

    assert result.full_model_name == "yaml-model"
    assert result.context_window == 12345
    assert result.logging_level == 30
    assert result.prompt_history_filename == "custom_history"
    assert result.history_dir == "history_dir"


def test_load_config_yaml_falls_back_to_defaults_when_no_user_config_exists(monkeypatch, tmp_path) -> None:
    """Verify the thin wrapper returns default config values when no user config exists."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))

    loader = ConfigLoader()
    result = loader.load_config_yaml()

    assert result.full_model_name == DEFAULT_MODEL
    assert result.context_window == 400_000
    assert result.prompt_history_filename == "prompt_history"
    assert result.history_dir == "history"
    assert result.logging_level == 20


def test_load_model_config_delegates_to_model_loader_and_returns_runtime_values(monkeypatch, tmp_path) -> None:
    """Verify the thin wrapper delegates model loading and returns resolved model config values."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_yaml = config_dir / "config.yaml"
    config_yaml.write_text("model: provider-family/model-x\n", encoding="utf-8")

    expected_model_config = object()

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))

    class DummyModelConfigLoader:
        def __init__(self, *args, **kwargs) -> None:
            self.load_calls: list[str] = []

        def load_model_config(self, model_name: str):
            self.load_calls.append(model_name)
            return expected_model_config

    monkeypatch.setattr(config_loader_module, "ModelConfigLoader", DummyModelConfigLoader)

    loader = ConfigLoader()
    loaded_model_config = loader.load_model_config("provider-family/model-x")

    assert loaded_model_config is expected_model_config


def test_load_config_v2_prefers_user_json_over_packaged_json(monkeypatch, tmp_path) -> None:
    """Verify the wrapper honors user model_config_v2.json over the packaged schema file."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_yaml = config_dir / "config.yaml"
    config_yaml.write_text("model: provider-family/model-x\n", encoding="utf-8")

    user_json = config_dir / "model_config_v2.json"
    user_json.write_text(
        """
{
  "model_mapping": {
    "provider-family/model-x": "user-alias"
  },
  "conversation_history_mapping": {
    "user-alias": 75
  },
  "context_window_mapping": {
    "user-alias": 256000
  },
  "output_window_mapping": {
    "user-alias": 32000
  },
  "model_max_tpm": {
    "user-alias": 12000
  },
  "xai_model_tpm_tier": {
    "user-alias": {
      "default": {
        "tpm": 12000
      }
    }
  }
}
""".strip(),
        encoding="utf-8",
    )

    expected_model_config = object()

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))

    class DummyModelConfigLoader:
        def __init__(self, *args, **kwargs) -> None:
            self.load_calls: list[str] = []

        def load_model_config(self, model_name: str):
            self.load_calls.append(model_name)
            return expected_model_config

    monkeypatch.setattr(config_loader_module, "ModelConfigLoader", DummyModelConfigLoader)

    loader = ConfigLoader()
    loaded_model_config = loader.load_model_config("provider-family/model-x")

    assert loaded_model_config is expected_model_config
