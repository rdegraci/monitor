"""Tests for the model config loader."""
from __future__ import annotations

from pathlib import Path

import appdirs

from monitor_oop.core.infrastructure.model_config_loader import ModelConfigLoader


def test_load_model_config_resolves_model_mapping_and_runtime_windows(monkeypatch, tmp_path) -> None:
    """Verify the committed schema maps a selected model to stable runtime config values."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    user_json = config_dir / "model_config_v2.json"
    user_json.write_text(
        """
{
  "model_mapping": {
    "provider-family/model-x": "model-x-alias"
  },
  "conversation_history_mapping": {
    "model-x-alias": 50
  },
  "context_window_mapping": {
    "model-x-alias": 128000
  },
  "output_window_mapping": {
    "model-x-alias": 16000
  },
  "model_max_tpm": {
    "model-x-alias": 9000
  }
}
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    loader = ModelConfigLoader()
    loaded_model_config = loader.load_model_config("provider-family/model-x")

    assert loaded_model_config.model_alias == "model-x-alias"
    assert loaded_model_config.full_model_name == "provider-family/model-x"
    assert loaded_model_config.context_window == 128000
    assert loaded_model_config.output_window == 16000
    assert loaded_model_config.conversation_turn_budget == 50
    assert loaded_model_config.tokens_per_minute == 9000


def test_load_config_v2_prefers_user_json_over_packaged_json(monkeypatch, tmp_path) -> None:
    """Verify user model_config_v2.json overrides the packaged schema file."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
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
  }
}
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    loader = ModelConfigLoader()
    loaded_model_config = loader.load_model_config("provider-family/model-x")

    assert loaded_model_config.model_alias == "user-alias"
    assert loaded_model_config.full_model_name == "provider-family/model-x"
    assert loaded_model_config.context_window == 256000
    assert loaded_model_config.output_window == 32000
    assert loaded_model_config.conversation_turn_budget == 75
    assert loaded_model_config.tokens_per_minute == 12000
