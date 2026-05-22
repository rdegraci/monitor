"""Public-API tests for monitor.lib.find_files.find_files.

Uses real tempdirs (filesystem state as the test boundary) rather than
mocking pathlib or os.walk — matches the codebase's testing rules.
"""

import os
import shutil
import tempfile
import unittest

from monitor.lib.find_files import find_files, MAX_RESULTS


class TestFindFiles(unittest.TestCase):
    """Verifies the public contract of find_files against real tempdir layouts."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def _touch(self, relative_path: str, content: str = "") -> None:
        """Create a file under self.tmpdir, including parent dirs."""
        full = os.path.join(self.tmpdir, relative_path)
        parent = os.path.dirname(full)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(full, "w") as f:
            f.write(content)

    def test_basename_pattern_matches_recursively(self):
        self._touch("a.py")
        self._touch("sub/b.py")
        self._touch("sub/deep/c.py")
        self._touch("d.txt")

        result = find_files(pattern="*.py", root=self.tmpdir)

        self.assertIsNone(result["error"])
        self.assertEqual(result["count"], 3)
        self.assertEqual(set(result["results"]), {"a.py", "sub/b.py", "sub/deep/c.py"})
        self.assertFalse(result["truncated"])

    def test_excluded_dirs_pruned_by_default(self):
        self._touch("kept.py")
        self._touch("node_modules/leaf.py")
        self._touch(".git/config.py")
        self._touch("__pycache__/cached.py")
        self._touch("Pods/library.py")
        self._touch("DerivedData/build.py")

        result = find_files(pattern="*.py", root=self.tmpdir)

        self.assertEqual(result["results"], ["kept.py"])

    def test_include_hidden_picks_up_dotfiles_and_dotdirs(self):
        self._touch("visible.py")
        self._touch(".hidden.py")
        self._touch(".somedir/inside.py")

        result = find_files(pattern="*.py", root=self.tmpdir, include_hidden=True)

        self.assertEqual(
            set(result["results"]),
            {"visible.py", ".hidden.py", ".somedir/inside.py"},
        )

    def test_max_results_caps_output_and_sets_truncated(self):
        for i in range(10):
            self._touch(f"file_{i:02d}.py")

        result = find_files(pattern="*.py", root=self.tmpdir, max_results=3)

        self.assertEqual(result["count"], 3)
        self.assertTrue(result["truncated"])

    def test_pattern_with_slash_is_rejected(self):
        # Patterns containing '/' would have surprising semantics with fnmatch
        # (`*` crosses `/`); the tool rejects them and points to `root` instead.
        self._touch("tests/test_a.py")

        result = find_files(pattern="tests/*.py", root=self.tmpdir)

        self.assertEqual(result["count"], 0)
        self.assertIn("/", result["error"])
        self.assertIn("root", result["error"])

    def test_root_argument_scopes_search_to_subdirectory(self):
        self._touch("tests/test_a.py")
        self._touch("tests/sub/test_b.py")
        self._touch("src/test_c.py")  # outside tests/

        result = find_files(pattern="test_*.py", root=os.path.join(self.tmpdir, "tests"))

        self.assertIsNone(result["error"])
        self.assertEqual(set(result["results"]), {"test_a.py", "sub/test_b.py"})

    def test_leading_double_star_slash_is_stripped(self):
        self._touch("deep/path/to/foo.swift")
        self._touch("foo.swift")

        result = find_files(pattern="**/*.swift", root=self.tmpdir)

        self.assertEqual(set(result["results"]), {"foo.swift", "deep/path/to/foo.swift"})

    def test_empty_pattern_returns_error_without_walking(self):
        self._touch("a.py")  # would otherwise be matched

        result = find_files(pattern="", root=self.tmpdir)

        self.assertEqual(result["count"], 0)
        self.assertIn("non-empty", result["error"])

    def test_nonexistent_root_returns_error(self):
        result = find_files(pattern="*.py", root="/nonexistent/path/that/does/not/exist")

        self.assertEqual(result["count"], 0)
        self.assertIn("not a directory", result["error"])

    def test_default_max_results_constant_in_result(self):
        # Sanity: when nothing matches, count is 0 and truncated is False.
        self._touch("file.txt")

        result = find_files(pattern="*.nonexistent", root=self.tmpdir)

        self.assertEqual(result["count"], 0)
        self.assertFalse(result["truncated"])
        self.assertIsNone(result["error"])

    def test_root_field_is_absolute_path(self):
        self._touch("x.py")

        result = find_files(pattern="*.py", root=self.tmpdir)

        self.assertTrue(os.path.isabs(result["root"]))


if __name__ == "__main__":
    unittest.main()
