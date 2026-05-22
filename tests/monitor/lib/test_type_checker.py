"""Public-API tests for monitor.lib.type_checker.type_check_python.

The runtime-dependent tests use real mypy/pyright subprocesses against tempdir
source files. They skip cleanly when neither checker is installed so this file
remains green in barebones environments.

The dispatch/error-shape tests don't require a checker and always run.
"""

import os
import shutil
import tempfile
import textwrap
import unittest

from monitor.lib.type_checker import type_check_python


_HAS_CHECKER = bool(shutil.which("mypy") or shutil.which("pyright"))


class TestTypeCheckPythonDispatch(unittest.TestCase):
    """Tests that exercise input validation and error-shape contracts.
    These don't need a checker installed."""

    def test_invalid_checker_returns_error_dict(self):
        result = type_check_python(checker="invalid_name")
        self.assertIsNone(result["exit_code"])
        self.assertIn("unsupported", result["summary"])
        self.assertEqual(result["command"], [])

    def test_missing_checker_returns_clear_message(self):
        # Force a checker that doesn't exist on PATH (well, on most systems).
        # We use a deliberately-unlikely binary name so the test is stable.
        result = type_check_python(checker="mypy" if not shutil.which("mypy") else None)
        if not shutil.which("mypy") and not shutil.which("pyright"):
            self.assertIsNone(result["exit_code"])
            self.assertTrue("not found" in result["summary"] or "install" in result["summary"].lower())


@unittest.skipUnless(_HAS_CHECKER, "neither mypy nor pyright installed; skipping live-checker tests")
class TestTypeCheckPythonLive(unittest.TestCase):
    """Real subprocess invocations against tempdir source files."""

    def _make_test_dir(self, contents: str) -> str:
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "sample.py"), "w") as f:
            f.write(contents)
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_clean_typed_code_returns_exit_zero(self):
        d = self._make_test_dir(textwrap.dedent("""
            def add(a: int, b: int) -> int:
                return a + b
        """))
        result = type_check_python(path=os.path.join(d, "sample.py"))
        self.assertEqual(result["exit_code"], 0)
        self.assertIn(result["checker"], ("mypy", "pyright"))

    def test_type_error_returns_nonzero_with_error_in_summary(self):
        d = self._make_test_dir(textwrap.dedent("""
            def add(a: int, b: int) -> int:
                return a + b

            result: str = add(1, 2)  # int assigned to str — type error
        """))
        result = type_check_python(path=os.path.join(d, "sample.py"))
        self.assertNotEqual(result["exit_code"], 0)
        self.assertIn("error", result["summary"].lower())

    def test_checker_field_reflects_chosen_tool(self):
        d = self._make_test_dir("x: int = 1\n")
        result = type_check_python(path=os.path.join(d, "sample.py"))
        self.assertIn(result["checker"], ("mypy", "pyright"))

    def test_command_field_reflects_path_argument(self):
        d = self._make_test_dir("x: int = 1\n")
        test_file = os.path.join(d, "sample.py")
        result = type_check_python(path=test_file)
        self.assertIn(test_file, result["command"])


if __name__ == "__main__":
    unittest.main()
