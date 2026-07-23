"""Tests for live turn/tool activity feedback (PLAN Phase 3)."""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from monitor import config
from monitor.lib import activity


class TestActivityFormatting(unittest.TestCase):
    def test_format_activity_waiting_after_tool(self):
        text = activity.format_activity(
            activity.STATE_WAITING,
            rt_count=3,
            tool="run_python_tests",
        )
        self.assertEqual(text, "RT 3 · run_python_tests · processing results")

    def test_running_state_not_labeled_but_others_are(self):
        running = activity.format_activity(activity.STATE_RUNNING, rt_count=1, tool="cat_file")
        self.assertNotIn("running", running)
        waiting = activity.format_activity(activity.STATE_WAITING, rt_count=1)
        self.assertEqual(waiting, "RT 1 · pre-processing")
        waiting_with_tool = activity.format_activity(
            activity.STATE_WAITING, rt_count=2, tool="ripgrep_search_tool"
        )
        self.assertEqual(
            waiting_with_tool, "RT 2 · ripgrep_search_tool · processing results"
        )

    def test_format_activity_omits_missing_fields(self):
        text = activity.format_activity(activity.STATE_WAITING, rt_count=2)
        self.assertEqual(text, "RT 2 · pre-processing")

    def test_retrying_keeps_state_label(self):
        text = activity.format_activity(
            activity.STATE_RETRYING, rt_count=2, tool="modify_source_code"
        )
        self.assertEqual(text, "RT 2 · modify_source_code · retrying")


class TestActivityGating(unittest.TestCase):
    def setUp(self):
        self._orig = getattr(config, "LIVE_TURN_FEEDBACK", True)
        config.LIVE_TURN_FEEDBACK = True
        activity.clear()

    def tearDown(self):
        config.LIVE_TURN_FEEDBACK = self._orig
        activity.clear()

    def test_feedback_disabled_by_config(self):
        config.LIVE_TURN_FEEDBACK = False
        self.assertFalse(activity.feedback_enabled())

    def test_feedback_disabled_in_server_mode(self):
        with patch.object(config, "SERVER_MODE", True):
            self.assertFalse(activity.feedback_enabled())

    def test_feedback_disabled_in_agent_mode(self):
        with patch.object(config, "AGENT", True):
            self.assertFalse(activity.feedback_enabled())

    def test_show_records_text_even_without_tty(self):
        # Non-TTY: no stderr paint, but text is tracked for the TUI surface.
        buf = io.StringIO()
        with patch("monitor.lib.activity.sys.stderr", buf):
            activity.show(activity.STATE_RUNNING, rt_count=1, tool="cat_file")
        self.assertIsNotNone(activity.current_activity())
        self.assertIn("cat_file", activity.current_activity())
        self.assertEqual(buf.getvalue(), "")

    def test_show_running_does_not_paint_even_when_forced(self):
        class _TTY(io.StringIO):
            def isatty(self):
                return True

        buf = _TTY()
        with patch("monitor.lib.activity.sys.stderr", buf), patch.dict(
            "os.environ", {"MONITOR_FORCE_PROGRESS": "1"}
        ):
            activity.show(activity.STATE_RUNNING, rt_count=2, tool="run_python_tests")
        self.assertEqual(activity.current_activity(), "RT 2 · run_python_tests")
        self.assertEqual(buf.getvalue(), "")

    def test_show_waiting_uses_last_tool(self):
        activity.show(activity.STATE_RUNNING, rt_count=1, tool="ripgrep_search_tool")
        activity.show(activity.STATE_WAITING, rt_count=2)
        self.assertEqual(
            activity.current_activity(),
            "RT 2 · ripgrep_search_tool · processing results",
        )

    def test_show_waiting_without_prior_tool(self):
        activity.show(activity.STATE_WAITING, rt_count=1)
        self.assertEqual(activity.current_activity(), "RT 1 · pre-processing")

    def test_show_noop_when_disabled(self):
        config.LIVE_TURN_FEEDBACK = False
        activity.show(activity.STATE_RUNNING, rt_count=1, tool="cat_file")
        self.assertIsNone(activity.current_activity())

    def test_clear_resets_tracked_text_and_last_tool(self):
        activity.show(activity.STATE_RUNNING, rt_count=1, tool="cat_file")
        activity.clear()
        self.assertIsNone(activity.current_activity())
        activity.show(activity.STATE_WAITING, rt_count=1)
        self.assertEqual(activity.current_activity(), "RT 1 · pre-processing")

    def test_suspend_paint_keeps_tracked_text(self):
        class _TTY(io.StringIO):
            def isatty(self):
                return True

        buf = _TTY()
        with patch("monitor.lib.activity.sys.stderr", buf), patch.dict(
            "os.environ", {"MONITOR_FORCE_PROGRESS": "1"}
        ):
            # WAITING paints; RUNNING does not. suspend after a painted wait.
            activity.show(activity.STATE_WAITING, rt_count=1)
            activity.show(activity.STATE_RUNNING, rt_count=1, tool="ripgrep_search_tool")
            self.assertIn("ripgrep_search_tool", activity.current_activity())
            activity.suspend_paint()
        self.assertEqual(activity.current_activity(), "RT 1 · ripgrep_search_tool")

    def test_progress_dots_uses_activity_label(self):
        from monitor.lib.progress import progress_dots

        class _TTY(io.StringIO):
            def isatty(self):
                return True

        activity.show(activity.STATE_WAITING, rt_count=3)
        buf = _TTY()
        with patch("monitor.lib.progress.sys.stderr", buf), patch.dict(
            "os.environ", {"MONITOR_FORCE_PROGRESS": "1"}
        ), patch("monitor.lib.progress._INITIAL_DELAY_SECONDS", 0):
            with progress_dots():
                import time

                time.sleep(0.25)
        out = buf.getvalue()
        self.assertIn("RT 3", out)
        self.assertIn("pre-processing", out)

    def test_progress_dots_uses_last_tool_label(self):
        from monitor.lib.progress import progress_dots

        class _TTY(io.StringIO):
            def isatty(self):
                return True

        activity.show(activity.STATE_RUNNING, rt_count=1, tool="modify_source_code")
        activity.show(activity.STATE_WAITING, rt_count=2)
        buf = _TTY()
        with patch("monitor.lib.progress.sys.stderr", buf), patch.dict(
            "os.environ", {"MONITOR_FORCE_PROGRESS": "1"}
        ), patch("monitor.lib.progress._INITIAL_DELAY_SECONDS", 0):
            with progress_dots():
                import time

                time.sleep(0.25)
        out = buf.getvalue()
        self.assertIn("RT 2", out)
        self.assertIn("modify_source_code", out)
        self.assertIn("processing results", out)
        self.assertNotIn("pre-processing", out)

    def test_show_waiting_paints_when_forced_tty(self):
        class _TTY(io.StringIO):
            def isatty(self):
                return True

        buf = _TTY()
        with patch("monitor.lib.activity.sys.stderr", buf), patch.dict(
            "os.environ", {"MONITOR_FORCE_PROGRESS": "1"}
        ):
            activity.show(activity.STATE_RUNNING, rt_count=1, tool="run_python_tests")
            activity.show(activity.STATE_WAITING, rt_count=2)
        out = buf.getvalue()
        self.assertIn("run_python_tests", out)
        self.assertIn("RT 2", out)
        self.assertNotIn("input", out)
        self.assertNotIn("$", out)


class TestActivityCommand(unittest.TestCase):
    def setUp(self):
        self._orig = getattr(config, "LIVE_TURN_FEEDBACK", True)

    def tearDown(self):
        config.LIVE_TURN_FEEDBACK = self._orig

    def test_command_off_on_toggle(self):
        from monitor.lib.built_in_commands import activity_command

        config.LIVE_TURN_FEEDBACK = True
        activity_command("off")
        self.assertFalse(config.LIVE_TURN_FEEDBACK)
        activity_command("on")
        self.assertTrue(config.LIVE_TURN_FEEDBACK)
        activity_command("toggle")
        self.assertFalse(config.LIVE_TURN_FEEDBACK)

    def test_command_show_does_not_change_state(self):
        from monitor.lib.built_in_commands import activity_command

        config.LIVE_TURN_FEEDBACK = True
        activity_command("")
        self.assertTrue(config.LIVE_TURN_FEEDBACK)


class TestActivityNeverLeaksPayload(unittest.TestCase):
    def test_show_only_receives_tool_name(self):
        # The public API accepts a tool NAME only; ensure arbitrary args/paths
        # are not part of the rendered text.
        text = activity.format_activity(
            activity.STATE_RUNNING,
            rt_count=1,
            tool="modify_source_code",
        )
        self.assertNotIn("/", text)  # no path payload
        self.assertEqual(text, "RT 1 · modify_source_code")


if __name__ == "__main__":
    unittest.main()
