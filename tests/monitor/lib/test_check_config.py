"""Tests for Phase 8 configuration check and first-run seeding."""

from __future__ import annotations

import pytest

from monitor.lib import check_config
from monitor import __main__ as main_module


def test_check_configuration_masks_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-should-never-appear")
    monkeypatch.setattr("monitor.config.MODEL", "openai/gpt-4o-mini", raising=False)
    monkeypatch.setattr("monitor.config.TOOL_PROFILE", "coding", raising=False)
    monkeypatch.setattr("monitor.config.STATUS_LINE_MODE", "coding", raising=False)
    monkeypatch.setattr("monitor.config.DAILY_COST_TARGET_USD", 5.0, raising=False)

    (tmp_path / "config.yaml").write_text("MODEL: x\n", encoding="utf-8")
    report = check_config.check_configuration(config_dir=str(tmp_path))
    text = check_config.format_check_report(report)

    assert "sk-secret" not in text
    assert "OPENAI_API_KEY" in text
    assert ": set" in text or "] OpenAI" in text
    assert report.ok is True


def test_check_configuration_errors_without_provider_keys(monkeypatch, tmp_path):
    for _label, env_name in check_config._PROVIDER_KEY_ENV:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr("monitor.config.MODEL", "openai/gpt-4o-mini", raising=False)
    monkeypatch.setattr("monitor.config.TOOL_PROFILE", "coding", raising=False)
    monkeypatch.setattr("monitor.config.DAILY_COST_TARGET_USD", 5.0, raising=False)

    report = check_config.check_configuration(config_dir=str(tmp_path))
    assert report.ok is False
    text = check_config.format_check_report(report)
    assert "no known provider key" in text
    assert "ERROR" in text


def test_seed_user_config_files_does_not_overwrite(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module.appdirs, "user_config_dir", lambda *_a, **_k: str(tmp_path))
    monkeypatch.setattr(main_module.config, "SESSIONS_FOLDER", "sessions", raising=False)

    existing = tmp_path / "config.yaml"
    existing.write_text("user-custom: true\n", encoding="utf-8")

    seeded = main_module.seed_user_config_files()
    assert "config.yaml" not in seeded
    assert existing.read_text(encoding="utf-8") == "user-custom: true\n"
    assert (tmp_path / "macros.json").is_file()
    assert "macros.json" in seeded


def test_seed_user_config_files_empty_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module.appdirs, "user_config_dir", lambda *_a, **_k: str(tmp_path))
    monkeypatch.setattr(main_module.config, "SESSIONS_FOLDER", "sessions", raising=False)

    seeded = main_module.seed_user_config_files()
    expected = [dest for _src, dest in check_config.SEEDED_CONFIG_FILES]
    for dest in expected:
        assert (tmp_path / dest).is_file(), dest
        assert dest in seeded
    assert (tmp_path / "sessions").is_dir()


def test_check_config_cli_exits(monkeypatch):
    import monitor.app as app_module

    monkeypatch.setattr(
        "sys.argv",
        ["monitor", "--check-config"],
    )
    monkeypatch.setattr(app_module, "load_model_config", lambda: None)
    monkeypatch.setattr(app_module, "load_environment_globals", lambda: None)
    monkeypatch.setattr(app_module, "start_logging", lambda: None)
    monkeypatch.setattr(
        "monitor.lib.check_config.print_check_report",
        lambda: 0,
    )
    with pytest.raises(SystemExit) as exc:
        app_module.main()
    assert exc.value.code == 0
