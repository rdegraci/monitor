"""Tests for EnvLoader in the Monitor OOP infrastructure layer."""
from __future__ import annotations

import os

from monitor._stubs import appdirs

from monitor_oop.core.infrastructure import env_loader as env_loader_module
from monitor_oop.core.infrastructure.env_loader import EnvLoader
from monitor_oop.core.models import RuntimeConfig


def test_load_env_loads_project_then_user_then_fallback(monkeypatch, tmp_path) -> None:
    """Verify dotenv files are loaded in the expected precedence order."""

    project_env = tmp_path / ".env"
    user_config_dir = tmp_path / "user-config"
    user_config_dir.mkdir()
    user_env = user_config_dir / ".env"
    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(user_config_dir))
    monkeypatch.setattr(env_loader_module, "find_dotenv", lambda usecwd=True: str(project_env))

    expected_fallback_env = tmp_path / ".config" / "monitor" / ".env"
    monkeypatch.setattr(
        env_loader_module.os.path,
        "expanduser",
        lambda path: str(expected_fallback_env) if path == "~/.config/monitor/.env" else path,
    )

    fallback_env = expected_fallback_env
    fallback_env.parent.mkdir(parents=True)
    project_env.write_text("PROJECT=1\n", encoding="utf-8")
    user_env.write_text("USER=1\n", encoding="utf-8")
    fallback_env.write_text("FALLBACK=1\n", encoding="utf-8")

    def fake_exists(path):
        return path in {str(user_env), str(fallback_env), str(expected_fallback_env)}

    monkeypatch.setattr(env_loader_module.os.path, "exists", fake_exists)

    calls = []

    def fake_load_dotenv(dotenv_path, override=False):
        calls.append((dotenv_path, override))
        return True

    monkeypatch.setattr(env_loader_module, "load_dotenv", fake_load_dotenv)

    loader = EnvLoader()
    loader.load_env()

    assert [call[0] for call in calls].index(str(project_env)) < [call[0] for call in calls].index(str(user_env))
    assert [call[0] for call in calls].index(str(user_env)) < [call[0] for call in calls].index(str(expected_fallback_env))
    assert str(project_env) in [call[0] for call in calls]
    assert str(user_env) in [call[0] for call in calls]
    assert str(expected_fallback_env) in [call[0] for call in calls]
    assert all(override is True for _, override in calls)


def test_apply_environment_overrides_updates_runtime_config(monkeypatch) -> None:
    """Verify environment variables override config values and API key is preserved."""

    monkeypatch.setenv("MODEL", "anthropic/claude")
    monkeypatch.setenv("CONTEXT_WINDOW", "999")
    monkeypatch.setenv("LOG_LEVEL", "30")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    loader = EnvLoader()
    config = RuntimeConfig(full_model_name="fallback-model")
    result = loader.apply_environment_overrides(config, current_openai_api_key="fallback-key")

    assert config.full_model_name == "anthropic/claude"
    assert config.context_window == 999
    assert result.openai_api_key == "env-key"
    assert result.logging_level == 30


def test_apply_environment_overrides_falls_back_to_current_api_key(monkeypatch) -> None:
    """Verify the previous API key is restored when the environment is empty."""

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("CONTEXT_WINDOW", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    loader = EnvLoader()
    config = RuntimeConfig(full_model_name="fallback-model")
    result = loader.apply_environment_overrides(config, current_openai_api_key="fallback-key")

    assert result.openai_api_key == "fallback-key"
    assert os.environ["OPENAI_API_KEY"] == "fallback-key"
    assert result.logging_level == 20
