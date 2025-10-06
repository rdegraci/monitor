import os
import shutil
import appdirs
import importlib.resources
import importlib.util

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

def main():
    ensure_user_config_file("config.yaml","config.yaml")
    ensure_user_config_file("macros.json","macros.json")
    ensure_user_config_file("preferences.prompt","preferences.prompt")
    ensure_user_config_file("model_config.json", "model_config.json")
    ensure_user_config_file("non_interactive_commands.json", "non_interactive_commands.json")
    ensure_user_config_file("interactive_commands.json", "interactive_commands.json")
    app_main()

if __name__ == "__main__":
    main()
