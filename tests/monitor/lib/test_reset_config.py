import os
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
from types import SimpleNamespace

import monitor.app as app_module


class DummyCM:
    def __init__(self, path):
        self._path = path

    def __enter__(self):
        return self._path

    def __exit__(self, exc_type, exc, tb):
        return False


class TestResetConfigBackupTimestamp(unittest.TestCase):
    def test_reset_config_creates_utc_backup_with_z(self):
        """Ensure _reset_config backs up existing files with UTC timestamp ending in Z."""
        # Create a temporary user config dir and a dummy existing config file
        tmp_dir = tempfile.mkdtemp(prefix="monitor_test_cfg_")
        try:
            user_config_dir = tmp_dir
            filename = "config.yaml"
            user_file_path = os.path.join(user_config_dir, filename)
            with open(user_file_path, "w", encoding="utf-8") as f:
                f.write("original-content")

            # Create a temporary default resource file to be copied into user dir
            default_resource = tempfile.NamedTemporaryFile(delete=False)
            default_resource_path = default_resource.name
            default_resource.close()
            with open(default_resource_path, "w", encoding="utf-8") as f:
                f.write("default-content")

            # Prepare a fixed UTC time
            fixed_dt = datetime(2025, 1, 2, 3, 4, 5)

            # Patches: appdirs.user_config_dir -> our tmp dir
            # importlib.resources.path -> context manager yielding default_resource_path
            with patch("monitor.app.appdirs.user_config_dir", return_value=user_config_dir), \
                 patch("monitor.app.importlib.resources.path", side_effect=lambda pkg, name: DummyCM(default_resource_path)), \
                 patch("monitor.app.datetime", new=SimpleNamespace(utcnow=lambda: fixed_dt)):
                # Call reset_config with force=True. It will sys.exit(0) at the end; catch SystemExit.
                with self.assertRaises(SystemExit) as cm_exit:
                    app_module._reset_config(force=True)
                self.assertEqual(cm_exit.exception.code, 0)

            # Verify backup file exists with expected UTC timestamp format ending in Z
            expected_suffix = ".bak_" + fixed_dt.strftime("%Y%m%dT%H%M%SZ")
            backup_files = [f for f in os.listdir(user_config_dir) if f.endswith(expected_suffix)]
            self.assertTrue(len(backup_files) >= 1, f"Expected backup file with suffix {expected_suffix}, found: {os.listdir(user_config_dir)}")

            # Verify the original filename has been replaced by the default content
            with open(user_file_path, "r", encoding="utf-8") as f:
                copied = f.read()
            self.assertEqual(copied, "default-content")

        finally:
            # Cleanup
            try:
                # remove files in dir
                for name in os.listdir(tmp_dir):
                    path = os.path.join(tmp_dir, name)
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                os.rmdir(tmp_dir)
            except Exception:
                pass
            try:
                os.remove(default_resource_path)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
