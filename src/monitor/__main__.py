import importlib.resources
import importlib.util
import os
import shutil
from pathlib import Path

from monitor._stubs import appdirs
from monitor import config

from .app import main as app_main

def ensure_user_config_file(src_filename, dest_filename):
    config_dir = appdirs.user_config_dir("monitor")
    os.makedirs(config_dir, exist_ok=True)
    dest = os.path.join(config_dir, dest_filename)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not os.path.exists(dest):
        resource = importlib.resources.files("monitor").joinpath(src_filename)
        with importlib.resources.as_file(resource) as src:
            shutil.copy(str(src), dest)
        print(f"Copied default {src_filename} to {dest}")

def _initialize_session_artifacts() -> None:
    """Initialize the active session artifacts at startup."""
    from monitor.lib.built_ins_history_utils import reset_conversation_history_command

    reset_conversation_history_command(emit_notice=False)


def main():
    ensure_user_config_file("config.yaml.example", "config.yaml")
    sessions_root = Path(appdirs.user_config_dir("monitor")) / config.SESSIONS_FOLDER
    sessions_root.mkdir(parents=True, exist_ok=True)
    ensure_user_config_file("macros.json", "macros.json")
    ensure_user_config_file("preferences.prompt","preferences.prompt")
    ensure_user_config_file("model_config.json", "model_config.json")
    ensure_user_config_file("non_interactive_commands.json", "non_interactive_commands.json")
    ensure_user_config_file("interactive_commands.json", "interactive_commands.json")
    ensure_user_config_file("directives/echo.prompt", "directives/echo.prompt")
    ensure_user_config_file("directives/greet.prompt", "directives/greet.prompt")
    sessions_root.mkdir(parents=True, exist_ok=True)
    _initialize_session_artifacts()
    app_main()

if __name__ == "__main__":
    main()
