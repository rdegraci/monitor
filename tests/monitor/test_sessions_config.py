import importlib
from pathlib import Path

import pytest

from monitor._stubs import appdirs


@pytest.fixture()
def config_module():
    """Import the monitor config module fresh for each test.

    Returns:
        The reloaded config module.
    """
    module = importlib.import_module("monitor.config")
    return importlib.reload(module)


def test_configure_globals_loads_sessions_folder(monkeypatch, config_module):
    """Verify SESSIONS_FOLDER is loaded from YAML into module state."""
    yaml_payload = {
        "MODEL": "demo/model",
        "MODEL_CONTEXT_WINDOW": 1000,
        "MODEL_OUTPUT_WINDOW": 100,
        "SESSIONS_FOLDER": "custom-sessions",
    }
    monkeypatch.setattr(config_module, "load_yaml_config", lambda file_path=None: yaml_payload)
    config_module.configure_globals()
    assert config_module.SESSIONS_FOLDER == "custom-sessions"


def test_main_creates_sessions_root(monkeypatch, tmp_path):
    """Verify startup creates the sessions root under the user config dir."""
    created = []

    def fake_user_config_dir(_appname):
        return str(tmp_path)

    def fake_ensure(src_filename, dest_filename):
        created.append((src_filename, dest_filename))

    def fake_reset_history(*args, **kwargs):
        (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)

    main_module = importlib.import_module("monitor.__main__")
    monkeypatch.setattr(appdirs, "user_config_dir", fake_user_config_dir)
    monkeypatch.setattr(main_module, "ensure_user_config_file", fake_ensure)
    monkeypatch.setattr(main_module, "app_main", lambda: None)
    monkeypatch.setattr(
        "monitor.lib.built_ins_history_utils.reset_conversation_history_command",
        fake_reset_history,
    )

    main_module.main()

    assert (tmp_path / "sessions").is_dir()
    assert created[0] == ("config.yaml.example", "config.yaml")
