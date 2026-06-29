import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import re

import monitor.lib.logging as app_logging
from monitor._stubs import appdirs


class TestLoggingConfig(unittest.TestCase):
    def test_inject_pid_into_logfile_path(self):
        # With placeholder
        p = app_logging._inject_pid_into_logfile_path("/tmp/app_{pid}.log", pid=123)
        self.assertEqual(p, "/tmp/app_123.log")
        # Without placeholder, with extension
        p2 = app_logging._inject_pid_into_logfile_path("/tmp/app.log", pid=456)
        self.assertEqual(p2, "/tmp/app_456.log")
        # Without extension
        p3 = app_logging._inject_pid_into_logfile_path("/tmp/app", pid=7)
        self.assertEqual(p3, "/tmp/app_7")

    @patch("monitor.lib.logging.RotatingFileHandler")
    @patch("monitor.lib.logging.os.makedirs")
    def test_configure_logging_basic(self, mock_makedirs, mock_file_handler):
        # Prepare a temp path with placeholder
        tmp_dir = tempfile.gettempdir()
        file_path = os.path.join(tmp_dir, "test_app_{pid}.log")
        fake_config = SimpleNamespace(
            LOGGING_LEVEL="DEBUG",
            LOG_FILE_PATH=file_path,
            LOG_FORMAT="%(levelname)s|%(message)s",
            LOG_DATE_FORMAT="%H:%M:%S",
            LOG_MAX_BYTES=12345,
            LOG_BACKUP_COUNT=2,
            CONSOLE_LOGGING_ENABLED=True,
            LOG_ENCODING="utf-8",
        )
        with patch.object(app_logging, "config", fake_config):
            # Ensure clean root logger
            root = app_logging.logging.getLogger()
            for h in root.handlers[:]:
                root.removeHandler(h)
            mock_file_handler.return_value.level = app_logging.logging.NOTSET
            app_logging.configure_logging()

        # File handler constructed with pid-substituted path
        called_path = mock_file_handler.call_args.kwargs.get("filename") or mock_file_handler.call_args.args[0]
        self.assertIn("test_app_", called_path)
        self.assertTrue(called_path.endswith(".log"))
        # Root logger should have a StreamHandler for console
        handlers = app_logging.logging.getLogger().handlers
        self.assertTrue(any(isinstance(h, app_logging.logging.StreamHandler) for h in handlers))

    @patch("monitor.lib.logging.RotatingFileHandler")
    @patch("monitor.lib.logging.os.makedirs")
    def test_configure_logging_console_disabled(self, mock_makedirs, mock_file_handler):
        tmp_dir = tempfile.gettempdir()
        file_path = os.path.join(tmp_dir, "test_app2_{pid}.log")
        fake_config = SimpleNamespace(
            LOGGING_LEVEL="INFO",
            LOG_FILE_PATH=file_path,
            LOG_FORMAT="%(message)s",
            LOG_DATE_FORMAT="%S",
            LOG_MAX_BYTES=1000,
            LOG_BACKUP_COUNT=1,
            CONSOLE_LOGGING_ENABLED=False,
            LOG_ENCODING="utf-8",
        )
        with patch.object(app_logging, "config", fake_config):
            # Clear handlers and configure
            root = app_logging.logging.getLogger()
            for h in root.handlers[:]:
                root.removeHandler(h)
            mock_file_handler.return_value.level = app_logging.logging.NOTSET
            app_logging.configure_logging()

        handlers = app_logging.logging.getLogger().handlers
        # Only file handler should be added by our code (plus any leftovers cleared)
        # Since we patched RotatingFileHandler, we can't check type directly.
        # Ensure that there is no StreamHandler
        self.assertFalse(any(isinstance(h, app_logging.logging.StreamHandler) for h in handlers))

    @patch("monitor.lib.logging.RotatingFileHandler")
    @patch("monitor.lib.logging.os.makedirs")
    def test_configure_logging_idempotent(self, mock_makedirs, mock_file_handler):
        tmp_dir = tempfile.gettempdir()
        file_path = os.path.join(tmp_dir, "test_app3_{pid}.log")
        fake_config = SimpleNamespace(
            LOGGING_LEVEL="WARNING",
            LOG_FILE_PATH=file_path,
            LOG_FORMAT="%(message)s",
            LOG_DATE_FORMAT="%S",
            LOG_MAX_BYTES=2000,
            LOG_BACKUP_COUNT=1,
            CONSOLE_LOGGING_ENABLED=True,
            LOG_ENCODING="utf-8",
        )
        with patch.object(app_logging, "config", fake_config):
            root = app_logging.logging.getLogger()
            for h in root.handlers[:]:
                root.removeHandler(h)
            mock_file_handler.return_value.level = app_logging.logging.NOTSET
            app_logging.configure_logging()
            # Record number of handlers added
            first_count = len(root.handlers)
            app_logging.configure_logging()
            second_count = len(root.handlers)
        # Handler count should remain stable across repeated calls
        self.assertEqual(first_count, second_count)
        self.assertGreaterEqual(mock_file_handler.call_count, 2)

    @patch("monitor.lib.logging.RotatingFileHandler")
    @patch("monitor.lib.logging.os.makedirs")
    def test_default_log_directory_used(self, mock_makedirs, mock_file_handler):
        # Simulate config without LOG_FILE_PATH by setting it to None
        fake_config = SimpleNamespace(
            LOGGING_LEVEL="INFO",
            LOG_FILE_PATH=None,
            LOG_FORMAT="%(message)s",
            LOG_DATE_FORMAT="%S",
            LOG_MAX_BYTES=1000,
            LOG_BACKUP_COUNT=1,
            CONSOLE_LOGGING_ENABLED=False,
            LOG_ENCODING="utf-8",
        )
        with patch.object(app_logging, "config", fake_config):
            # Clear handlers and configure
            root = app_logging.logging.getLogger()
            for h in root.handlers[:]:
                root.removeHandler(h)
            mock_file_handler.return_value.level = app_logging.logging.NOTSET
            app_logging.configure_logging()

        called_path = mock_file_handler.call_args.kwargs.get("filename") or mock_file_handler.call_args.args[0]
        base_dir = appdirs.user_config_dir("monitor")
        expected_logs_dir = os.path.join(base_dir, "logs")
        # Ensure the constructed path contains the default 'logs' directory under the app config dir
        self.assertIn(expected_logs_dir, called_path)
        # Ensure log filename contains 'app' (default app log filename) and an injected pid (digits)
        basename = os.path.basename(called_path)
        self.assertIn("app", basename)
        self.assertRegex(basename, r"_\d+")

    def test_get_logger_returns_named_logger(self):
        logger = app_logging.get_logger("monitor.test")
        self.assertIsInstance(logger, app_logging.logging.Logger)
        # Ensure we can emit a log without error
        logger.debug("debug message")


if __name__ == "__main__":
    unittest.main()
