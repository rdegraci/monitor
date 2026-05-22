"""Public-API tests for monitor.lib.test_runner.run_python_tests.

These tests exercise the real subprocess + pytest path against tempdir test
files rather than mocking internals — matches the codebase's testing rules
(no monkeypatching of subprocess, shutil, or low-level OS primitives).

Each test costs ~0.3-0.7s of wall-clock time because it spawns a real pytest
subprocess. Total overhead for this file: ~3-4s. Acceptable.
"""

import os
import shutil
import tempfile
import textwrap
import unittest

from monitor.lib.test_runner import MAX_OUTPUT_CHARS, run_python_tests


class TestRunPythonTests(unittest.TestCase):
    """Verifies the public contract of run_python_tests against real pytest runs."""

    def _make_test_dir(self, contents: str) -> str:
        """Create a tempdir containing a single test_sample.py with the given source."""
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "test_sample.py"), "w") as f:
            f.write(contents)
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_passing_test_returns_exit_zero_and_passed_in_summary(self):
        d = self._make_test_dir(textwrap.dedent("""
            def test_passes():
                assert 1 + 1 == 2
        """))
        result = run_python_tests(path=os.path.join(d, "test_sample.py"))
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("passed", result["summary"])
        self.assertFalse(result["truncated"])

    def test_failing_test_returns_nonzero_with_failed_in_summary_and_traceback_in_output(self):
        d = self._make_test_dir(textwrap.dedent("""
            def test_fails():
                assert 1 + 1 == 3
        """))
        result = run_python_tests(path=os.path.join(d, "test_sample.py"))
        self.assertNotEqual(result["exit_code"], 0)
        self.assertIn("failed", result["summary"])
        # The traceback from the failing assertion should be present in the output
        self.assertIn("assert", result["output"])

    def test_invalid_pytest_args_type_returns_error_without_invoking_subprocess(self):
        # Passing a non-list pytest_args should be caught at the boundary;
        # the tool returns a structured error and never invokes pytest.
        result = run_python_tests(path="tests/", pytest_args="not a list")
        self.assertIsNone(result["exit_code"])
        self.assertIn("must be a list", result["summary"])
        self.assertEqual(result["command"], [])

    def test_tail_truncation_when_output_exceeds_budget(self):
        # A failing test that prints a huge captured-stdout block, pushing
        # output past MAX_OUTPUT_CHARS so we can verify tail-preserving truncation.
        big_blob = "X" * (MAX_OUTPUT_CHARS + 2000)
        d = self._make_test_dir(textwrap.dedent(f"""
            def test_dumps_a_lot():
                print({big_blob!r})
                assert False, "trailing_marker"
        """))
        result = run_python_tests(path=os.path.join(d, "test_sample.py"))
        self.assertTrue(result["truncated"])
        # Truncation marker is prepended
        self.assertTrue(result["output"].startswith("... [output truncated"))
        # The end-of-output (failure summary line) is preserved
        self.assertIn("failed", result["output"])

    def test_no_tests_collected_returns_pytest_exit_five(self):
        # File with no test_* functions → pytest exits 5 (NO_TESTS_COLLECTED).
        d = self._make_test_dir(textwrap.dedent("""
            def helper_not_a_test():
                return 42
        """))
        result = run_python_tests(path=os.path.join(d, "test_sample.py"))
        self.assertEqual(result["exit_code"], 5)

    def test_command_field_reflects_actual_invocation(self):
        d = self._make_test_dir("def test_pass(): assert True\n")
        test_file = os.path.join(d, "test_sample.py")
        result = run_python_tests(path=test_file, pytest_args=["-x"])
        self.assertIn(test_file, result["command"])
        self.assertIn("-x", result["command"])


if __name__ == "__main__":
    unittest.main()
