"""Tests for the isolated Monitor OOP config service."""
import os

import appdirs
import pytest

import monitor_oop.core.config_service as config_module
from monitor_oop.core.app import MonitorApp
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.llm_service import LLMService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.models import DEFAULT_MODEL, RuntimeConfig
from monitor_oop.core.runtime_context import RuntimeContext
from monitor_oop.core.status_service import StatusService


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


def test_config_service_load_env_loads_user_config_file(monkeypatch, tmp_path) -> None:
    """Verify load() loads the project and user config .env files in order."""

    project_env = tmp_path / ".env"
    project_env.write_text("PROJECT=value\n", encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    user_env = config_dir / ".env"
    user_env.write_text("EXAMPLE=value\n", encoding="utf-8")

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))
    monkeypatch.setattr(config_module, "find_dotenv", lambda *args, **kwargs: str(project_env))

    captured = []

    def fake_load_dotenv(dotenv_path, override=False):
        captured.append((dotenv_path, override))
        return True

    monkeypatch.setattr(config_module, "load_dotenv", fake_load_dotenv)

    service = ConfigService()
    service.load()

    attempted_paths = {str(path) for path, _ in captured}
    assert str(project_env) in attempted_paths
    assert str(user_env) in attempted_paths
    assert any(str(path) == str(user_env) and override is True for path, override in captured)


def test_config_service_load_env_populates_openai_api_key(monkeypatch, tmp_path) -> None:
    """Verify load() resolves OPENAI_API_KEY from loaded .env files with user precedence."""

    project_env = tmp_path / ".env"
    project_env.write_text("OPENAI_API_KEY=project-key\n", encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    user_env = config_dir / ".env"
    user_env.write_text("OPENAI_API_KEY=user-key\n", encoding="utf-8")

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))
    monkeypatch.setattr(config_module, "find_dotenv", lambda *args, **kwargs: str(project_env))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fake_load_dotenv(dotenv_path, override=False):
        if dotenv_path == str(project_env):
            os.environ["OPENAI_API_KEY"] = "project-key"
        elif dotenv_path == str(user_env):
            if override:
                os.environ["OPENAI_API_KEY"] = "user-key"
        return True

    monkeypatch.setattr(config_module, "load_dotenv", fake_load_dotenv)

    service = ConfigService()
    service.load()

    assert os.environ["OPENAI_API_KEY"] == "user-key"
    assert service.get_openai_api_key() == "user-key"


def test_config_service_load_config_yaml_creates_example_copy(monkeypatch, tmp_path) -> None:
    """Verify load() creates config.yaml from the example file on first run."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    packaged_example_yaml = tmp_path / "src" / "monitor_oop" / "config.yaml.example"
    packaged_example_yaml.parent.mkdir(parents=True)
    packaged_example_yaml.write_text("model: example-model\ncontext_window: 999\nlogging_level: 10\n", encoding="utf-8")

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))
    monkeypatch.setattr(config_module, "find_dotenv", lambda *args, **kwargs: "")
    monkeypatch.setattr(config_module, "__file__", str(tmp_path / "src" / "monitor_oop" / "config_service.py"))
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    service = ConfigService()
    service.load()

    config_yaml = config_dir / "config.yaml"
    assert config_yaml.exists()


def test_config_service_load_config_yaml_loads_runtime_values(monkeypatch, tmp_path) -> None:
    """Verify load() resolves model, context window, and logging level from YAML."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_yaml = config_dir / "config.yaml"
    config_yaml.write_text(
        "model: yaml-model\ncontext_window: 12345\nlogging_level: 20\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))
    monkeypatch.setattr(config_module, "find_dotenv", lambda *args, **kwargs: "")
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    service = ConfigService()
    service.load()

    assert service.get_model() == "yaml-model"
    assert service.get_context_window() == 12345
    assert service.get_logging_level() == 20


def test_config_service_load_config_yaml_prefers_env_log_level(monkeypatch, tmp_path) -> None:
    """Verify LOG_LEVEL from the environment overrides YAML logging_level."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_yaml = config_dir / "config.yaml"
    config_yaml.write_text(
        "model: yaml-model\ncontext_window: 12345\nlogging_level: 20\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(appdirs, "user_config_dir", lambda *args, **kwargs: str(config_dir))
    monkeypatch.setattr(config_module, "find_dotenv", lambda *args, **kwargs: "")
    monkeypatch.setenv("LOG_LEVEL", "warning")
    monkeypatch.setattr(config_module, "load_dotenv", lambda *args, **kwargs: True)

    service = ConfigService()
    service.load_config_yaml()
    service.load_env()

    assert service.get_model() == "yaml-model"
    assert service.get_context_window() == 12345
    assert service.get_logging_level() == 20


def test_monitor_app_run_returns_non_zero_when_openai_api_key_missing(monkeypatch, capsys) -> None:
    """Verify MonitorApp.run() fails clearly when OPENAI_API_KEY is absent."""

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    config_service = ConfigService()
    config_service._openai_api_key = None
    context = RuntimeContext(
        config_service=config_service,
        history_service=HistoryService(config_service),
        llm_service=LLMService(config_service),
        macro_service=MacroService(config_service),
        status_service=StatusService(),
        command_processor=object(),
    )
    app = MonitorApp(context)
    exit_code = app.run()

    captured = capsys.readouterr()

    assert exit_code != 0
    assert captured.err == "" or "missing" in captured.err.lower() or "not set" in captured.err.lower()
