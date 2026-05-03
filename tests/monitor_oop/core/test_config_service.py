"""Tests for the isolated Monitor OOP config service."""
import os

import appdirs
import pytest

from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.models import DEFAULT_MODEL, RuntimeConfig


def test_config_service_defaults() -> None:
    """Verify the default configuration service state."""

    service = ConfigService()

    assert service.get_model() == DEFAULT_MODEL
    assert service.get_context_window() == 400_000
    assert service.get_provider() == "openai"


def test_config_service_select_model_updates_state() -> None:
    """Verify model selection updates the runtime config."""

    service = ConfigService(initial_config=RuntimeConfig(model_name="base"))

    assert service.select_model("gpt-4") is True
    assert service.get_model() == "gpt-4"


def test_config_service_select_model_rejects_empty_name() -> None:
    """Verify empty model names are rejected."""

    service = ConfigService()

    assert service.select_model("") is False
    assert service.get_model() == DEFAULT_MODEL


def test_config_service_get_provider_from_prefixed_model_name() -> None:
    """Verify provider extraction from provider-prefixed model names."""

    service = ConfigService(initial_config=RuntimeConfig(model_name="anthropic/claude-3"))

    assert service.get_provider() == "anthropic"


def test_config_service_get_openai_api_key_defaults_to_none(monkeypatch) -> None:
    """Verify the service accessor returns no API key before loading env files."""

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    service = ConfigService()

    assert service.get_openai_api_key() is None


def test_config_service_load_smoke(monkeypatch, tmp_path) -> None:
    """Verify load() orchestrates env and config loading without exercising internals."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()

    project_env = tmp_path / ".env"
    user_env = config_dir / ".env"
    config_yaml = config_dir / "config.yaml"

    project_env.write_text("OPENAI_API_KEY=project-key\n", encoding="utf-8")
    user_env.write_text("OPENAI_API_KEY=user-key\n", encoding="utf-8")
    config_yaml.write_text("model: smoke-model\ncontext_window: 123\nlogging_level: 20\n", encoding="utf-8")

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))

    service = ConfigService()

    config_loader_calls = []
    env_loader_calls = []

    original_load_config_yaml = service._config_loader.load_config_yaml
    original_load_env = service._env_loader.load_env
    original_apply_environment_overrides = service._env_loader.apply_environment_overrides

    def fake_load_config_yaml(*args, **kwargs):
        config_loader_calls.append((args, kwargs))
        return original_load_config_yaml(*args, **kwargs)

    def fake_load_env(*args, **kwargs):
        env_loader_calls.append(("load_env", args, kwargs))
        return original_load_env(*args, **kwargs)

    def fake_apply_environment_overrides(*args, **kwargs):
        env_loader_calls.append(("apply_environment_overrides", args, kwargs))
        return original_apply_environment_overrides(*args, **kwargs)

    monkeypatch.setattr(service._config_loader, "load_config_yaml", fake_load_config_yaml)
    monkeypatch.setattr(service._env_loader, "load_env", fake_load_env)
    monkeypatch.setattr(service._env_loader, "apply_environment_overrides", fake_apply_environment_overrides)

    service.load()

    assert config_loader_calls
    assert env_loader_calls
    assert any(call[0] == "load_env" for call in env_loader_calls)
    assert any(call[0] == "apply_environment_overrides" for call in env_loader_calls)
