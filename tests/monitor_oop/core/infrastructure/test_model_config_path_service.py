"""Tests for model config path resolution helpers."""
from __future__ import annotations

import json

import appdirs
import pytest

from monitor_oop.core.infrastructure.model_config_path_service import (
    ModelConfigPathService,
)


def test_load_json_config_reads_valid_json_from_user_config(monkeypatch, tmp_path) -> None:
    """Verify JSON loading returns the parsed mapping from user config."""

    user_config_dir = tmp_path / "user-config"
    user_config_dir.mkdir()
    config_path = user_config_dir / "model_config_v2.json"
    config_path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(user_config_dir))

    service = ModelConfigPathService(app_name="monitor")

    assert service.load_json_config() == {"hello": "world"}


def test_load_json_config_rejects_non_object_json_from_user_config(monkeypatch, tmp_path) -> None:
    """Verify JSON loading rejects non-object user config content."""

    user_config_dir = tmp_path / "user-config"
    user_config_dir.mkdir()
    config_path = user_config_dir / "model_config_v2.json"
    config_path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(user_config_dir))

    service = ModelConfigPathService(app_name="monitor")

    with pytest.raises(ValueError, match="model configuration must be a dictionary"):
        service.load_json_config()
