"""Tests for the model config loader."""
from __future__ import annotations

from pathlib import Path

from monitor._stubs import appdirs

from monitor_oop.core.infrastructure.model_config_loader import ModelConfigLoader


def write_packaged_model_config(packaged_json: Path, *, model_alias: str, conversation_turn_budget: int, context_window: int, output_window: int, tokens_per_minute: int) -> None:
    packaged_json.write_text(
        f"""
{{
  "model_mapping": {{
    "provider-family/model-x": "{model_alias}"
  }},
  "conversation_history_mapping": {{
    "{model_alias}": {conversation_turn_budget}
  }},
  "context_window_mapping": {{
    "{model_alias}": {context_window}
  }},
  "output_window_mapping": {{
    "{model_alias}": {output_window}
  }},
  "model_max_tpm": {{
    "{model_alias}": "tpm-tiers/standard"
  }},
  "model_max_rpm": {{
    "{model_alias}": "rpm-tiers/standard"
  }},
  "tpm-tiers": {{
    "standard": {tokens_per_minute}
  }},
  "rpm-tiers": {{
    "standard": 120
  }}
}}
""".strip(),
        encoding="utf-8",
    )


def write_user_model_config(user_json: Path, *, model_alias: str, conversation_turn_budget: int, context_window: int, output_window: int, tokens_per_minute: int) -> None:
    user_json.write_text(
        f"""
{{
  "model_mapping": {{
    "provider-family/model-x": "{model_alias}"
  }},
  "conversation_history_mapping": {{
    "{model_alias}": {conversation_turn_budget}
  }},
  "context_window_mapping": {{
    "{model_alias}": {context_window}
  }},
  "output_window_mapping": {{
    "{model_alias}": {output_window}
  }},
  "model_max_tpm": {{
    "{model_alias}": "tpm-tiers/premium"
  }},
  "model_max_rpm": {{
    "{model_alias}": "rpm-tiers/premium"
  }},
  "tpm-tiers": {{
    "premium": {tokens_per_minute}
  }},
  "rpm-tiers": {{
    "premium": 180
  }}
}}
""".strip(),
        encoding="utf-8",
    )


def test_load_model_config_prefers_packaged_json_when_no_user_config_exists(monkeypatch, tmp_path) -> None:
    """Verify the loader falls back to packaged config when no user config exists."""

    packaged_root = tmp_path / "packaged"
    packaged_root.mkdir()
    packaged_json = packaged_root / "model_config_v2.json"
    write_packaged_model_config(
        packaged_json,
        model_alias="packaged-alias",
        conversation_turn_budget=25,
        context_window=64000,
        output_window=8000,
        tokens_per_minute=6000,
    )

    user_config_dir = tmp_path / "config"
    user_config_dir.mkdir()

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(user_config_dir))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(ModelConfigLoader, "get_packaged_config_path", lambda self: packaged_json)

    loader = ModelConfigLoader()
    loaded_model_config = loader.load_model_config("provider-family/model-x")

    assert loaded_model_config.model_alias == "packaged-alias"
    assert loaded_model_config.full_model_name == "provider-family/model-x"
    assert loaded_model_config.context_window == 64000
    assert loaded_model_config.output_window == 8000
    assert loaded_model_config.conversation_turn_budget == 25
    assert loaded_model_config.tokens_per_minute == 6000


def test_load_config_v2_prefers_user_json_over_packaged_json(monkeypatch, tmp_path) -> None:
    """Verify user model_config_v2.json overrides the packaged schema file."""

    packaged_root = tmp_path / "packaged"
    packaged_root.mkdir()
    packaged_json = packaged_root / "model_config_v2.json"
    write_packaged_model_config(
        packaged_json,
        model_alias="packaged-alias",
        conversation_turn_budget=25,
        context_window=64000,
        output_window=8000,
        tokens_per_minute=6000,
    )

    user_config_dir = tmp_path / "config"
    user_config_dir.mkdir()
    user_json = user_config_dir / "model_config_v2.json"
    write_user_model_config(
        user_json,
        model_alias="user-alias",
        conversation_turn_budget=75,
        context_window=256000,
        output_window=32000,
        tokens_per_minute=12000,
    )

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(user_config_dir))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        ModelConfigLoader,
        "get_packaged_config_path",
        lambda self: packaged_json,
    )

    loader = ModelConfigLoader()
    loaded_model_config = loader.load_model_config("provider-family/model-x")

    assert loaded_model_config.model_alias == "user-alias"
    assert loaded_model_config.full_model_name == "provider-family/model-x"
    assert loaded_model_config.context_window == 256000
    assert loaded_model_config.output_window == 32000
    assert loaded_model_config.conversation_turn_budget == 75
    assert loaded_model_config.tokens_per_minute == 12000


def test_load_model_config_reads_user_config_when_it_exists(monkeypatch, tmp_path) -> None:
    """Verify the loader reads the user config path when it exists."""

    packaged_root = tmp_path / "packaged"
    packaged_root.mkdir()
    packaged_json = packaged_root / "model_config_v2.json"
    write_packaged_model_config(
        packaged_json,
        model_alias="packaged-alias",
        conversation_turn_budget=25,
        context_window=64000,
        output_window=8000,
        tokens_per_minute=6000,
    )

    user_config_dir = tmp_path / "config"
    user_config_dir.mkdir()
    user_json = user_config_dir / "model_config_v2.json"
    write_user_model_config(
        user_json,
        model_alias="user-alias",
        conversation_turn_budget=75,
        context_window=256000,
        output_window=32000,
        tokens_per_minute=12000,
    )

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(user_config_dir))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(ModelConfigLoader, "get_packaged_config_path", lambda self: packaged_json)

    loader = ModelConfigLoader()
    loaded_model_config = loader.load_model_config("provider-family/model-x")

    assert loaded_model_config.model_alias == "user-alias"
    assert loaded_model_config.full_model_name == "provider-family/model-x"
    assert loaded_model_config.context_window == 256000
    assert loaded_model_config.output_window == 32000
    assert loaded_model_config.conversation_turn_budget == 75
    assert loaded_model_config.tokens_per_minute == 12000
