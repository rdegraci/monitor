"""Tests for prompt storage and loading in Monitor OOP."""
from __future__ import annotations

from pathlib import Path

import appdirs

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.infrastructure.prompt_store import PromptStore
from monitor_oop.core.prompt_service import PromptService


def test_prompt_store_seeds_missing_prompt(monkeypatch, tmp_path) -> None:
    """Verify missing system prompt is seeded from the packaged example."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))

    config_service = ConfigService()
    store = PromptStore(config_service=config_service)
    prompt_text = store.load()

    assert prompt_text.strip()
    assert (config_dir / "system_prompt").exists()


def test_prompt_service_loads_prompt(monkeypatch, tmp_path) -> None:
    """Verify PromptService loads and exposes the resolved prompt text."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    prompt_path = config_dir / "system_prompt"
    prompt_path.write_text("Hello prompt", encoding="utf-8")
    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))

    config_service = ConfigService()
    prompt_store = PromptStore(config_service=config_service)
    service = PromptService(config_service=config_service, prompt_store=prompt_store)
    service.load()

    assert service.get_resolved_prompt_text() == "Hello prompt"
    assert service.get() == "Hello prompt"


def test_prompt_service_reload_updates_prompt(monkeypatch, tmp_path) -> None:
    """Verify PromptService reloads prompt content from disk."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    prompt_path = config_dir / "system_prompt"
    prompt_path.write_text("First prompt", encoding="utf-8")
    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))

    config_service = ConfigService()
    prompt_store = PromptStore(config_service=config_service)
    service = PromptService(config_service=config_service, prompt_store=prompt_store)
    service.load()
    prompt_path.write_text("Second prompt", encoding="utf-8")
    service.reload()

    assert service.get_resolved_prompt_text() == "Second prompt"
