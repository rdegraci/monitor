

import os
import appdirs
import shutil
import importlib.resources
import importlib.util

from .app import main

def ensure_user_config_file(src_filename, dest_filename):
    config_dir = appdirs.user_config_dir("monitor")
    os.makedirs(config_dir, exist_ok=True)
    dest = os.path.join(config_dir, dest_filename)
    if not os.path.exists(dest):
        with importlib.resources.path("monitor", src_filename) as src:
            shutil.copy(str(src), dest)
        print(f"Copied default {src_filename} to {dest}")

if __name__ == "__main__":
    ensure_user_config_file("dot_env_example", ".env")
    ensure_user_config_file("app.yaml", "app.yaml")
    ensure_user_config_file("macros.json", "macros.json")
    ensure_user_config_file("public_commands.json", "public_commands.json")
    main()



# def main():
#     print("hello world")

#     # 1. Print the installation path of the 'monitor' package
#     monitor_spec = importlib.util.find_spec('monitor')
#     print("\n[1] 'monitor' Package Installation Path:")
#     if monitor_spec and monitor_spec.origin:
#         print("Path:", monitor_spec.origin)
#     else:
#         print("Could not locate the 'monitor' package installation path.")

#     # 2. Try to access a bundled example config file/resource via importlib.resources
#     print("\n[2] Accessing bundled example resource 'example.cfg' from 'monitor':")
#     try:
#         if hasattr(importlib.resources, 'files'):
#             # Python 3.9+
#             resource = importlib.resources.files('monitor').joinpath('example.cfg')
#             if resource.is_file():
#                 with importlib.resources.as_file(resource) as res_path:
#                     with open(res_path, 'r') as f:
#                         content = f.read()
#                 print("Contents of bundled 'example.cfg':")
#                 print(content)
#             else:
#                 print("'example.cfg' not found in 'monitor' package resources.")
#         else:
#             # Python <3.9
#             with importlib.resources.open_text('monitor', 'example.cfg') as f:
#                 content = f.read()
#             print("Contents of bundled 'example.cfg':")
#             print(content)
#     except (FileNotFoundError, ImportError, ModuleNotFoundError):
#         print("'example.cfg' not found or 'monitor' package does not provide this resource.")
#     except Exception as e:
#         print(f"Error accessing 'example.cfg': {e}")

#     # 3. Print the user-specific config directory for 'monitor'
#     print("\n[3] User-Specific Config Directory for 'monitor':")
#     user_config_dir = appdirs.user_config_dir('monitor')
#     print("User config directory:", user_config_dir)
