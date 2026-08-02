"""Tests for FreeMicro Agent Key hook helper."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from monitor import config
from monitor.lib import freemicro


class TestFreemicroGating(unittest.TestCase):
    def setUp(self):
        self._orig = getattr(config, "FREEMICRO_HOOKS", False)
        freemicro._started = False
        freemicro._atexit_registered = False
        freemicro._binary_cache = None

    def tearDown(self):
        config.FREEMICRO_HOOKS = self._orig
        freemicro._started = False
        freemicro._atexit_registered = False
        freemicro._binary_cache = None

    def test_disabled_by_default_skips_subprocess(self):
        config.FREEMICRO_HOOKS = False
        with patch("monitor.lib.freemicro.subprocess.run") as run:
            freemicro.emit("UserPromptSubmit")
        run.assert_not_called()

    def test_enabled_emits_claude_shaped_payload(self):
        config.FREEMICRO_HOOKS = True
        config.SESSION_ID = "sess-test-1"
        with patch("monitor.lib.freemicro.shutil.which", return_value="/bin/freemicro"), patch(
            "monitor.lib.freemicro.subprocess.run"
        ) as run, patch("monitor.lib.freemicro.os.getcwd", return_value="/tmp/proj"):
            freemicro.emit("UserPromptSubmit")
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["/bin/freemicro", "hook"])
        payload = json.loads(kwargs["input"].decode("utf-8"))
        self.assertEqual(payload["hook_event_name"], "UserPromptSubmit")
        self.assertEqual(payload["session_id"], "sess-test-1")
        self.assertEqual(payload["cwd"], "/tmp/proj")
        self.assertEqual(payload["title"], "monitor")
        self.assertEqual(payload["pid"], os.getpid())
        self.assertEqual(kwargs["timeout"], freemicro._HOOK_TIMEOUT)
        self.assertFalse(kwargs["check"])

    def test_missing_binary_is_silent(self):
        config.FREEMICRO_HOOKS = True
        with patch("monitor.lib.freemicro.shutil.which", return_value=None), patch(
            "monitor.lib.freemicro.subprocess.run"
        ) as run:
            freemicro.emit("Stop")
        run.assert_not_called()

    def test_subprocess_failure_never_raises(self):
        config.FREEMICRO_HOOKS = True
        with patch("monitor.lib.freemicro.shutil.which", return_value="/bin/freemicro"), patch(
            "monitor.lib.freemicro.subprocess.run",
            side_effect=OSError("boom"),
        ):
            freemicro.emit("Stop")  # must not raise

    def test_stop_error_sets_is_error(self):
        config.FREEMICRO_HOOKS = True
        with patch("monitor.lib.freemicro.shutil.which", return_value="/bin/freemicro"), patch(
            "monitor.lib.freemicro.subprocess.run"
        ) as run:
            freemicro.stop(error=True)
        payload = json.loads(run.call_args.kwargs["input"].decode("utf-8"))
        self.assertEqual(payload["hook_event_name"], "Stop")
        self.assertTrue(payload["is_error"])

    def test_session_start_registers_atexit_once(self):
        config.FREEMICRO_HOOKS = True
        with patch("monitor.lib.freemicro.shutil.which", return_value="/bin/freemicro"), patch(
            "monitor.lib.freemicro.subprocess.run"
        ), patch("monitor.lib.freemicro.atexit.register") as register:
            freemicro.session_start()
            freemicro.session_start()
        register.assert_called_once_with(freemicro.session_end)

    def test_pre_tool_use_includes_tool_name(self):
        config.FREEMICRO_HOOKS = True
        with patch("monitor.lib.freemicro.shutil.which", return_value="/bin/freemicro"), patch(
            "monitor.lib.freemicro.subprocess.run"
        ) as run, patch("monitor.lib.freemicro.atexit.register"):
            freemicro.pre_tool_use("ripgrep_search_tool")
        # SessionStart + PreToolUse
        self.assertEqual(run.call_count, 2)
        payload = json.loads(run.call_args_list[-1].kwargs["input"].decode("utf-8"))
        self.assertEqual(payload["hook_event_name"], "PreToolUse")
        self.assertEqual(payload["tool_name"], "ripgrep_search_tool")


if __name__ == "__main__":
    unittest.main()
