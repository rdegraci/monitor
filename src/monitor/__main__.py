import importlib.resources
import os
import shutil
import sys
from pathlib import Path


def ensure_user_config_file(src_filename, dest_filename):
    """Copy a packaged default into the user config dir if missing.

    Returns:
        True when a new file was seeded, False when the destination already existed.
    """
    from monitor._stubs import appdirs

    config_dir = appdirs.user_config_dir("monitor")
    os.makedirs(config_dir, exist_ok=True)
    dest = os.path.join(config_dir, dest_filename)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        return False
    resource = importlib.resources.files("monitor").joinpath(src_filename)
    with importlib.resources.as_file(resource) as src:
        shutil.copy(str(src), dest)
    print(f"Copied default {src_filename} to {dest}")
    return True


def seed_user_config_files():
    """Seed all first-run config files. Never overwrites existing user files.

    Returns:
        list[str]: Destination basenames that were newly copied.
    """
    from monitor import config
    from monitor._stubs import appdirs
    from monitor.lib.check_config import SEEDED_CONFIG_FILES

    seeded = []
    for src, dest in SEEDED_CONFIG_FILES:
        if ensure_user_config_file(src, dest):
            seeded.append(dest)
    sessions_root = Path(appdirs.user_config_dir("monitor")) / config.SESSIONS_FOLDER
    sessions_root.mkdir(parents=True, exist_ok=True)
    return seeded


def _initialize_session_artifacts() -> None:
    """Initialize the active session artifacts at startup."""
    from monitor.lib.built_ins_history_utils import reset_conversation_history_command

    reset_conversation_history_command(emit_notice=False)


def _run_lightweight_cli(argv: list[str]) -> None:
    """Handle ``--status-all`` / ``--activate`` without importing the full app.

    Exits the process when a lightweight command is present.
    """
    if "--status-all" in argv:
        from monitor.lib.instances import print_status_all

        raise SystemExit(print_status_all())

    if "--activate" in argv:
        try:
            index = argv.index("--activate")
        except ValueError:
            return
        if index + 1 >= len(argv) or str(argv[index + 1]).startswith("-"):
            print(
                "Usage: monitor --activate TTY\n"
                "Examples: monitor --activate ttys002 | 002 | /dev/ttys002",
                file=sys.stderr,
            )
            raise SystemExit(2)
        from monitor.lib.instances import print_activate

        raise SystemExit(print_activate(argv[index + 1]))


def main():
    # Fast path: process/TTY utilities must not pay for stubs/app/session startup.
    _run_lightweight_cli(sys.argv[1:])

    seed_user_config_files()
    _initialize_session_artifacts()
    from .app import main as app_main

    app_main()


if __name__ == "__main__":
    main()
