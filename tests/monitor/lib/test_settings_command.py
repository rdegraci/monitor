import json

import monitor.config  # noqa: F401
from monitor import config
from monitor.core.built_ins import configure_built_ins
from monitor.lib.built_ins_runtime_utils import settings_command
from monitor.lib.built_ins_utils import is_built_in_function


def test_settings_command_is_registered_as_builtin():
    """Verify the built-in registry exposes :settings."""
    configure_built_ins()

    assert is_built_in_function(":settings") is not None
    assert is_built_in_function("/settings") is not None
    assert is_built_in_function("settings") is None


def test_settings_command_prints_mixed_key_dicts(monkeypatch, capsys):
    """Verify :settings handles nested dictionaries with mixed key types."""
    monkeypatch.setattr(
        config,
        "MIXED_KEY_TEST_SETTING",
        {"alpha": {1: "one", "2": "two"}, 3: ["x", {4: "y"}]},
        raising=False,
    )

    settings_command("mixed_key_test")

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["MIXED_KEY_TEST_SETTING"]["alpha"]["1"] == "one"
    assert payload["MIXED_KEY_TEST_SETTING"]["alpha"]["2"] == "two"
    assert payload["MIXED_KEY_TEST_SETTING"]["3"][1]["4"] == "y"


def test_settings_command_omits_excluded_keys(monkeypatch, capsys):
    """Verify :settings omits sensitive or noisy config keys."""
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [{"role": "user"}], raising=False)
    monkeypatch.setattr(config, "PROJECT_INSTRUCTIONS_CONTENT", "secret-ish", raising=False)
    monkeypatch.setattr(config, "FUNCTION_KEY_INSERTIONS", {"f1": "cmd"}, raising=False)
    monkeypatch.setattr(config, "_MODEL_CONFIG_CACHE", {"a": 1}, raising=False)
    monkeypatch.setattr(config, "VISIBLE_TEST_SETTING", "shown", raising=False)

    settings_command("")

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "CONVERSATION_HISTORY" not in payload
    assert "FUNCTION_KEY_INSERTIONS" not in payload
    assert "PROJECT_INSTRUCTIONS_CONTENT" not in payload
    assert "_MODEL_CONFIG_CACHE" not in payload
    assert "_VALID_REASONING_EFFORTS" not in payload
    assert payload["VISIBLE_TEST_SETTING"] == "shown"
