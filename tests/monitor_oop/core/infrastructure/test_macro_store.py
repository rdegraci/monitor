"""Tests for MacroStore in the Monitor OOP infrastructure layer."""
from __future__ import annotations

import json
from pathlib import Path

import appdirs

from monitor_oop.core.infrastructure import macro_store as macro_store_module
from monitor_oop.core.infrastructure.macro_store import MacroStore


def test_macro_store_loads_existing_macros(monkeypatch, tmp_path) -> None:
    """Verify MacroStore loads existing JSON macro definitions."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    macro_path = config_dir / "macros.json"
    macro_path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))

    store = MacroStore()
    assert store.load() == {"hello": "world"}


def test_macro_store_loads_packaged_example_for_missing_file(monkeypatch, tmp_path) -> None:
    """Verify MacroStore seeds missing user macros from the packaged example."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()

    example_path = Path(macro_store_module.__file__).with_name("macros.json.example")
    example_mapping = json.loads(example_path.read_text(encoding="utf-8"))

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))

    store = MacroStore()
    result = store.load()

    assert result == example_mapping
    assert (config_dir / "macros.json").exists()


def test_macro_store_returns_empty_dict_for_malformed_json(monkeypatch, tmp_path) -> None:
    """Verify MacroStore safely ignores malformed JSON input."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    macro_path = config_dir / "macros.json"
    macro_path.write_text("{not-json", encoding="utf-8")

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))

    store = MacroStore()
    assert store.load() == {}


def test_macro_store_seeds_from_packaged_example(monkeypatch, tmp_path) -> None:
    """Verify MacroStore seeds the user macro file from the packaged example."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()

    example_path = Path(macro_store_module.__file__).with_name("macros.json.example")
    example_mapping = json.loads(example_path.read_text(encoding="utf-8"))

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))

    store = MacroStore()
    result = store.load()

    assert result == example_mapping
    assert (config_dir / "macros.json").exists()
