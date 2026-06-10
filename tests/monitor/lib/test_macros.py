import unittest
import json
import tempfile
import os
from monitor import config
from unittest.mock import patch, mock_open, MagicMock
from io import StringIO
from monitor.lib import macros
import sys
import errno


class TestMacros(unittest.TestCase):
    """Test suite for macros module functions."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        # Save original macro values to restore after tests
        self.original_macro_values = macros.MACRO_VALUES.copy()
        self.original_ephemeral_values = macros.EPHEMERAL_MACRO_VALUES.copy()
        self.original_public_values = macros.PUBLIC_MACRO_VALUES.copy()
        self.original_private_values = macros.PRIVATE_MACRO_VALUES.copy()

    def tearDown(self):
        """Clean up after each test method."""
        # Restore original macro values
        macros.MACRO_VALUES.clear()
        macros.MACRO_VALUES.update(self.original_macro_values)
        macros.EPHEMERAL_MACRO_VALUES.clear()
        macros.EPHEMERAL_MACRO_VALUES.update(self.original_ephemeral_values)
        macros.PUBLIC_MACRO_VALUES.clear()
        macros.PUBLIC_MACRO_VALUES.update(self.original_public_values)
        macros.PRIVATE_MACRO_VALUES.clear()
        macros.PRIVATE_MACRO_VALUES.update(self.original_private_values)

    def test_ephemeral_macro_values_exist(self):
        """Test that ephemeral macro values are properly defined."""
        self.assertIsInstance(macros.EPHEMERAL_MACRO_VALUES, dict)
        self.assertEqual(len(macros.EPHEMERAL_MACRO_VALUES), 0)

    def test_private_macro_values_exist(self):
        """Test that private macro values are properly defined."""
        self.assertIsInstance(macros.PRIVATE_MACRO_VALUES, dict)
        expected_keys = ["system?", "memories?", "purpose?", "self_test"]
        self.assertEqual(len(macros.PRIVATE_MACRO_VALUES), 4)

        for key in expected_keys:
            self.assertIn(key, macros.PRIVATE_MACRO_VALUES)
            self.assertIsInstance(macros.PRIVATE_MACRO_VALUES[key], str)
            self.assertGreater(len(macros.PRIVATE_MACRO_VALUES[key]), 0)

    def test_public_macro_values_exist(self):
        """Test that public macro values are properly defined."""
        expected_keys = [
            "do_diff",
            "create_git_entry",
            "diff",
            "diff_previous",
            "xdiff",
            "rank_examine",
            "plan",
            "wdyt",
        ]

        for key in expected_keys:
            self.assertIn(key, macros.PUBLIC_MACRO_VALUES)
            self.assertIsInstance(macros.PUBLIC_MACRO_VALUES[key], str)

    def test_macro_values_contain_nested_references(self):
        """Test that some macro values contain references to other macros."""
        # Test that some macros reference other macros using configured delimiters or legacy parentheses syntax
        nested_macros = ["diff"]
        # Prepare candidate delimiter pairs: configured, default '{{','}}', and legacy '(' , ')'
        candidate_pairs = []
        configured_open = getattr(config, "MACRO_DELIMITER_OPEN", None)
        configured_close = getattr(config, "MACRO_DELIMITER_CLOSE", None)
        if configured_open is not None and configured_close is not None:
            candidate_pairs.append((configured_open, configured_close))
        # Always include defaults and legacy
        candidate_pairs.append(("{{", "}}"))
        candidate_pairs.append(("(", ")"))

        for macro in nested_macros:
            if macro in macros.PUBLIC_MACRO_VALUES:
                value = macros.PUBLIC_MACRO_VALUES[macro]
                contains_any = any(
                    (open_delim in value) and (close_delim in value)
                    for open_delim, close_delim in candidate_pairs
                )
                self.assertTrue(
                    contains_any,
                    "Macro '{}' should contain nested references using any of the configured delimiters, defaults '{{' '}}', or legacy parentheses".format(
                        macro
                    ),
                )

    @patch("monitor.lib.macros.update_macros")
    def test_configure_macros(self, mock_update_macros):
        """Test the configure_macros function."""
        mock_additional_macros = {"test_macro": "test_value"}
        with patch(
            "monitor.lib.macros.load_additional_macros",
            return_value=mock_additional_macros,
        ):
            macros.MACRO_VALUES.clear()
            macros.configure_macros()

            # MAC-4: new precedence (lowest → highest): public, file, ephemeral, private.
            # dict.update is last-wins, so ephemeral (runtime-added) now outranks
            # file-based macros on reload.
            expected_calls = [
                unittest.mock.call(macros.MACRO_VALUES, macros.PUBLIC_MACRO_VALUES),
                unittest.mock.call(macros.MACRO_VALUES, mock_additional_macros),
                unittest.mock.call(macros.MACRO_VALUES, macros.EPHEMERAL_MACRO_VALUES),
                unittest.mock.call(macros.MACRO_VALUES, macros.PRIVATE_MACRO_VALUES),
            ]
            self.assertEqual(mock_update_macros.call_count, 4)
            mock_update_macros.assert_has_calls(expected_calls)

    @patch("sys.stdout", new_callable=StringIO)
    def test_print_macros_grouped_output_includes_built_in_file_and_runtime_macros(
        self, mock_stdout
    ):
        """Test grouped macro display includes built-in, file, and runtime sections."""
        macros.PUBLIC_MACRO_VALUES.clear()
        macros.PUBLIC_MACRO_VALUES.update(
            {
                "built_in_macro": "built in description",
                "another_built_in": "another built in description",
            }
        )
        macros.EPHEMERAL_MACRO_VALUES.clear()
        macros.EPHEMERAL_MACRO_VALUES.update(
            {
                "runtime_macro": "runtime description",
            }
        )
        file_macros = {
            "file_macro": "file description",
        }

        with patch(
            "monitor.lib.macros.load_additional_macros",
            return_value=file_macros,
        ):
            with patch(
                "monitor.lib.macros.load_additional_macro_metadata",
                return_value={
                    "groups": {
                        "file": {
                            "title": "Macros file",
                            "description": "Persistent macros loaded from the configured macros file.",
                            "order": 200,
                        }
                    },
                    "macro_meta": {
                        "file_macro": {
                            "title": "File Macro",
                            "description": "file description",
                            "group": "file",
                        }
                    },
                },
            ):
                with patch("monitor.config.MACRO_FILE_PATH", "/dummy/path/for/test"):
                    macros.print_macros("test_arg")

        output = mock_stdout.getvalue()

        self.assertIn("Built-in macros", output)
        self.assertIn("Macros file", output)
        self.assertIn("Persistent macros loaded from the configured macros file.", output)
        self.assertIn("Runtime macros", output)
        self.assertIn("built_in_macro", output)
        self.assertIn("another_built_in", output)
        self.assertIn("file_macro", output)
        self.assertIn("runtime_macro", output)
        self.assertIn("file description", output)

    @patch("sys.stdout", new_callable=StringIO)
    def test_print_macros_grouped_output_shows_source_labels(self, mock_stdout):
        """Test grouped macro display renders source labels for visible macros."""
        macros.PUBLIC_MACRO_VALUES.clear()
        macros.PUBLIC_MACRO_VALUES.update({"built_in_macro": "built in description"})
        macros.EPHEMERAL_MACRO_VALUES.clear()
        macros.EPHEMERAL_MACRO_VALUES.update({"runtime_macro": "runtime description"})

        with patch(
            "monitor.lib.macros.load_additional_macros",
            return_value={"file_macro": "file description"},
        ):
            with patch(
                "monitor.lib.macros.load_additional_macro_metadata",
                return_value={
                    "groups": {},
                    "macro_meta": {
                        "file_macro": {
                            "title": "File Macro",
                            "description": "Loaded from file",
                            "group": "file",
                        }
                    },
                },
            ):
                with patch("monitor.config.MACRO_FILE_PATH", "/dummy/path/for/test"):
                    macros.print_macros("test_arg")

        output = mock_stdout.getvalue()

        self.assertIn("  Source: built-in", output)
        self.assertIn("  Source: file", output)
        self.assertIn("  Source: runtime", output)

    @patch("sys.stdout", new_callable=StringIO)
    def test_print_macros_grouped_output_excludes_private_macros_by_default(
        self, mock_stdout
    ):
        """Test grouped macro display excludes private macros unless explicitly enabled."""
        macros.PUBLIC_MACRO_VALUES.clear()
        macros.PUBLIC_MACRO_VALUES.update(
            {
                "public_macro": "public description",
            }
        )
        macros.EPHEMERAL_MACRO_VALUES.clear()
        macros.PRIVATE_MACRO_VALUES.clear()
        macros.PRIVATE_MACRO_VALUES.update(
            {
                "private_macro": "private description",
            }
        )

        with patch(
            "monitor.lib.macros.load_additional_macros",
            return_value={},
        ):
            with patch(
                "monitor.lib.macros.load_additional_macro_metadata",
                return_value={"groups": {}, "macro_meta": {}},
            ):
                with patch("monitor.config.MACRO_FILE_PATH", "/dummy/path/for/test"):
                    macros.print_macros("test_arg")

        output = mock_stdout.getvalue()

        self.assertIn("public_macro", output)
        self.assertNotIn("private_macro", output)
        self.assertNotIn("private description", output)

    @patch("sys.stdout", new_callable=StringIO)
    def test_print_macros_grouped_output_shows_titles_and_macro_descriptions(
        self, mock_stdout
    ):
        """Test grouped macro display shows section titles and human-readable values."""
        macros.PUBLIC_MACRO_VALUES.clear()
        macros.PUBLIC_MACRO_VALUES.update(
            {
                "summary_macro": "Summarize repository status",
            }
        )
        macros.EPHEMERAL_MACRO_VALUES.clear()

        with patch(
            "monitor.lib.macros.load_additional_macros",
            return_value={"local_macro": "Loaded from file"},
        ):
            with patch(
                "monitor.lib.macros.load_additional_macro_metadata",
                return_value={
                    "groups": {
                        "file": {
                            "title": "Macros file",
                            "description": "Persistent macros loaded from the configured macros file.",
                            "order": 200,
                        }
                    },
                    "macro_meta": {
                        "local_macro": {
                            "title": "Local Macro",
                            "description": "Loaded from file",
                            "group": "file",
                        }
                    },
                },
            ):
                with patch("monitor.config.MACRO_FILE_PATH", "/dummy/path/for/test"):
                    macros.print_macros("test_arg")

        output = mock_stdout.getvalue()

        self.assertIn("Built-in macros", output)
        self.assertIn("Macros file", output)
        self.assertIn("summary_macro", output)
        self.assertIn("local_macro", output)
        self.assertIn("Loaded from file", output)

    def test_print_macros_sets_less_r_inside_pager_and_restores_after(self):
        """Test macro paging enables ANSI passthrough in less and restores LESS."""
        macros.PUBLIC_MACRO_VALUES.clear()
        macros.PUBLIC_MACRO_VALUES.update({"public_macro": "public description"})
        macros.EPHEMERAL_MACRO_VALUES.clear()
        seen = {"less_during": None}

        with patch(
            "monitor.lib.macros.load_additional_macros",
            return_value={},
        ):
            with patch(
                "monitor.lib.macros.load_additional_macro_metadata",
                return_value={"groups": {}, "macro_meta": {}},
            ):
                with patch("monitor.config.MACRO_FILE_PATH", "/dummy/path/for/test"):
                    with patch.dict(os.environ, {"LESS": "user-custom-value"}, clear=False):
                        with patch("pydoc.pager") as mock_pager:
                            mock_pager.side_effect = lambda _text: seen.update(
                                {"less_during": os.environ.get("LESS")}
                            )
                            macros.print_macros("test_arg")
                        self.assertEqual(os.environ.get("LESS"), "user-custom-value")

        self.assertEqual(seen["less_during"], "-R")

    def test_print_macros_unsets_less_after_if_it_was_unset_before(self):
        """Test macro paging does not leak LESS when it was previously unset."""
        macros.PUBLIC_MACRO_VALUES.clear()
        macros.PUBLIC_MACRO_VALUES.update({"public_macro": "public description"})
        macros.EPHEMERAL_MACRO_VALUES.clear()

        with patch(
            "monitor.lib.macros.load_additional_macros",
            return_value={},
        ):
            with patch(
                "monitor.lib.macros.load_additional_macro_metadata",
                return_value={"groups": {}, "macro_meta": {}},
            ):
                with patch("monitor.config.MACRO_FILE_PATH", "/dummy/path/for/test"):
                    with patch.dict(os.environ, {}, clear=True):
                        with patch("pydoc.pager"):
                            macros.print_macros("test_arg")
                        self.assertNotIn("LESS", os.environ)

    def test_build_visible_macro_catalog_applies_file_group_metadata(self):
        """Test file-defined group metadata overrides fallback group headings."""
        macros.PUBLIC_MACRO_VALUES.clear()
        macros.EPHEMERAL_MACRO_VALUES.clear()

        with patch(
            "monitor.lib.macros.load_additional_macros",
            return_value={"branch": "branch value"},
        ):
            with patch(
                "monitor.lib.macros.load_additional_macro_metadata",
                return_value={
                    "groups": {
                        "git": {
                            "title": "Git Helpers",
                            "description": "Macros for repository inspection.",
                            "order": 25,
                        }
                    },
                    "macro_meta": {
                        "branch": {
                            "title": "Current Branch",
                            "description": "Returns the active branch.",
                            "group": "git",
                        }
                    },
                },
            ):
                with patch("monitor.config.MACRO_FILE_PATH", "/dummy/path/for/test"):
                    catalog, group_metadata = macros._build_visible_macro_catalog()

        branch_entry = next(entry for entry in catalog if entry["name"] == "branch")
        self.assertEqual(branch_entry["group"], "git")
        self.assertEqual(group_metadata["git"]["title"], "Git Helpers")
        self.assertEqual(
            group_metadata["git"]["description"],
            "Macros for repository inspection.",
        )
        self.assertEqual(group_metadata["git"]["order"], 25)
    def test_build_visible_macro_catalog_includes_suppression_prefixed_macros(self):
        """Test visible macro catalog includes macros whose names start with !<."""
        macros.PUBLIC_MACRO_VALUES.clear()
        macros.EPHEMERAL_MACRO_VALUES.clear()
        macros.EPHEMERAL_MACRO_VALUES.update(
            {
                "!<branch": "raw internal payload",
                "runtime_macro": "runtime description",
            }
        )

        with patch(
            "monitor.lib.macros.load_additional_macros",
            return_value={},
        ):
            with patch(
                "monitor.lib.macros.load_additional_macro_metadata",
                return_value={"groups": {}, "macro_meta": {}},
            ):
                with patch("monitor.config.MACRO_FILE_PATH", "/dummy/path/for/test"):
                    catalog, _ = macros._build_visible_macro_catalog()

        catalog_names = [entry["name"] for entry in catalog]
        self.assertIn("runtime_macro", catalog_names)
        self.assertIn("!<branch", catalog_names)

    def test_render_grouped_macro_catalog_colors_macro_names_yellow(self):
        """Test rendered macro names are wrapped in yellow ANSI color codes."""
        catalog = [
            {
                "name": "create_git_entry",
                "value": "ignored",
                "title": "Write git commit message",
                "description": "Generate a commit message.",
                "usage": "create_git_entry",
                "group": "built_in_general",
                "source": "public",
            }
        ]
        group_metadata = {
            "built_in_general": {
                "title": "Built-in macros",
                "description": "Useful built-in macros.",
                "order": 100,
            }
        }

        rendered = macros._render_grouped_macro_catalog(catalog, group_metadata)

        self.assertIn(f"{macros.yellow}create_git_entry{macros.reset}", rendered)

    def test_render_grouped_macro_catalog_colors_usage_magenta(self):
        """Test rendered usage values are wrapped in magenta ANSI color codes."""
        catalog = [
            {
                "name": "trace",
                "value": "ignored",
                "title": "Downstream Call Trace",
                "description": "Generate a project-only call tree.",
                "usage": "trace <function>",
                "group": "analysis",
                "source": "file",
            }
        ]
        group_metadata = {
            "analysis": {
                "title": "Analysis",
                "description": "Analysis macros.",
                "order": 100,
            }
        }

        rendered = macros._render_grouped_macro_catalog(catalog, group_metadata)

        self.assertIn(
            f"  Usage: {macros.magenta}trace <function>{macros.reset}",
            rendered,
        )

    def test_build_visible_macro_catalog_includes_usage_metadata(self):
        """Test visible macro catalog carries usage metadata from file macros."""
        with patch(
            "monitor.lib.macros.load_additional_macros",
            return_value={"trace": "macro body"},
        ):
            with patch(
                "monitor.lib.macros.load_additional_macro_metadata",
                return_value={
                    "groups": {},
                    "macro_meta": {
                        "trace": {
                            "title": "Downstream Call Trace",
                            "description": "Generate a project-only call tree.",
                            "usage": "trace <function>",
                            "group": "analysis",
                        }
                    },
                },
            ):
                with patch("monitor.config.MACRO_FILE_PATH", "/dummy/path/for/test"):
                    catalog, _ = macros._build_visible_macro_catalog()

        trace_entry = next(entry for entry in catalog if entry["name"] == "trace")
        self.assertEqual(trace_entry["usage"], "trace <function>")

    def test_build_visible_macro_catalog_ignores_invalid_group_order_type(self):
        """Test invalid group order metadata falls back instead of crashing."""
        macros.PUBLIC_MACRO_VALUES.clear()
        macros.EPHEMERAL_MACRO_VALUES.clear()

        with patch(
            "monitor.lib.macros.load_additional_macros",
            return_value={"branch": "branch value"},
        ):
            with patch(
                "monitor.lib.macros.load_additional_macro_metadata",
                return_value={
                    "groups": {
                        "git": {
                            "title": "Git Helpers",
                            "description": "Macros for repository inspection.",
                            "order": "first",
                        }
                    },
                    "macro_meta": {
                        "branch": {
                            "title": "Current Branch",
                            "description": "Returns the active branch.",
                            "group": "git",
                        }
                    },
                },
            ):
                with patch("monitor.config.MACRO_FILE_PATH", "/dummy/path/for/test"):
                    catalog, group_metadata = macros._build_visible_macro_catalog()

        branch_entry = next(entry for entry in catalog if entry["name"] == "branch")
        self.assertEqual(branch_entry["group"], "git")
        self.assertEqual(group_metadata["git"]["title"], "Git Helpers")
        self.assertEqual(group_metadata["git"]["order"], 500)

    def test_build_visible_macro_catalog_ignores_invalid_nested_group_metadata(self):
        """Test invalid nested group metadata falls back instead of crashing."""
        macros.PUBLIC_MACRO_VALUES.clear()
        macros.EPHEMERAL_MACRO_VALUES.clear()

        with patch(
            "monitor.lib.macros.load_additional_macros",
            return_value={"branch": "branch value"},
        ):
            with patch(
                "monitor.lib.macros.load_additional_macro_metadata",
                return_value={
                    "groups": {"git": []},
                    "macro_meta": {
                        "branch": {
                            "title": "Current Branch",
                            "description": "Returns the active branch.",
                            "group": "git",
                        }
                    },
                },
            ):
                with patch("monitor.config.MACRO_FILE_PATH", "/dummy/path/for/test"):
                    catalog, group_metadata = macros._build_visible_macro_catalog()

        branch_entry = next(entry for entry in catalog if entry["name"] == "branch")
        self.assertEqual(branch_entry["group"], "git")
        self.assertEqual(group_metadata["git"]["title"], "Git")
        self.assertEqual(group_metadata["git"]["description"], "")
        self.assertEqual(group_metadata["git"]["order"], 500)

    def test_build_visible_macro_catalog_ignores_invalid_nested_macro_metadata(self):
        """Test invalid nested macro metadata falls back instead of crashing."""
        macros.PUBLIC_MACRO_VALUES.clear()
        macros.EPHEMERAL_MACRO_VALUES.clear()

        with patch(
            "monitor.lib.macros.load_additional_macros",
            return_value={"branch": "branch value"},
        ):
            with patch(
                "monitor.lib.macros.load_additional_macro_metadata",
                return_value={
                    "groups": {},
                    "macro_meta": {"branch": "bad"},
                },
            ):
                with patch("monitor.config.MACRO_FILE_PATH", "/dummy/path/for/test"):
                    catalog, _ = macros._build_visible_macro_catalog()

        branch_entry = next(entry for entry in catalog if entry["name"] == "branch")
        self.assertEqual(branch_entry["title"], "branch")
        self.assertEqual(branch_entry["description"], "")
        self.assertEqual(branch_entry["usage"], "")
        self.assertEqual(branch_entry["group"], "file")

    def test_add_macro_definition_valid_format(self):
        """Test add_macro_definition with valid key=value format."""
        test_input = "<test_key=test_value"

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = macros.add_macro_definition(test_input)

        self.assertTrue(result)
        self.assertIn("test_key", macros.EPHEMERAL_MACRO_VALUES)
        self.assertEqual(macros.EPHEMERAL_MACRO_VALUES["test_key"], "test_value")

        output = mock_stdout.getvalue()
        self.assertIn("Added to macro_values", output)
        self.assertIn("'test_key'", output)
        self.assertIn("'test_value'", output)

    def test_add_macro_definition_with_spaces(self):
        """Test add_macro_definition with spaces around key and value."""
        test_input = "<  spaced_key  =  spaced_value  "

        result = macros.add_macro_definition(test_input)

        self.assertTrue(result)
        self.assertIn("spaced_key", macros.EPHEMERAL_MACRO_VALUES)
        self.assertEqual(macros.EPHEMERAL_MACRO_VALUES["spaced_key"], "spaced_value")

    def test_add_macro_definition_complex_value(self):
        """Test add_macro_definition with complex macro value."""
        test_input = "<complex_macro=examine (models_dir)(model).swift"

        result = macros.add_macro_definition(test_input)

        self.assertTrue(result)
        self.assertIn("complex_macro", macros.EPHEMERAL_MACRO_VALUES)
        self.assertEqual(
            macros.EPHEMERAL_MACRO_VALUES["complex_macro"],
            "examine (models_dir)(model).swift",
        )

    def test_add_macro_definition_invalid_format_no_equals(self):
        """Test add_macro_definition with invalid format (no equals sign)."""
        test_input = "<invalid_macro_without_equals"

        with patch("monitor.lib.macros.logger") as mock_logger:
            result = macros.add_macro_definition(test_input)

        self.assertFalse(result)
        mock_logger.error.assert_called_once()

        # Should not add anything to ephemeral_macro_values
        self.assertNotIn(
            "invalid_macro_without_equals", macros.EPHEMERAL_MACRO_VALUES
        )

    def test_add_macro_definition_invalid_format_multiple_equals(self):
        """Test add_macro_definition with multiple equals signs."""
        test_input = "<key=value=extra"

        result = macros.add_macro_definition(test_input)

        # Should still work, taking first split only
        self.assertTrue(result)
        self.assertIn("key", macros.EPHEMERAL_MACRO_VALUES)
        self.assertEqual(macros.EPHEMERAL_MACRO_VALUES["key"], "value=extra")

    def test_add_macro_definition_empty_key(self):
        """Test add_macro_definition with empty key."""
        test_input = "<=test_value"

        result = macros.add_macro_definition(test_input)

        self.assertTrue(result)
        self.assertIn("", macros.EPHEMERAL_MACRO_VALUES)
        self.assertEqual(macros.EPHEMERAL_MACRO_VALUES[""], "test_value")

    def test_add_macro_definition_empty_value(self):
        """Test add_macro_definition with empty value."""
        test_input = "<test_key="

        result = macros.add_macro_definition(test_input)

        self.assertTrue(result)
        self.assertIn("test_key", macros.EPHEMERAL_MACRO_VALUES)
        self.assertEqual(macros.EPHEMERAL_MACRO_VALUES["test_key"], "")

    @patch("monitor.lib.macros.update_macros")
    def test_add_macro_definition_calls_update_macros(self, mock_update_macros):
        """Test that add_macro_definition calls update_macros."""
        test_input = "<test_key=test_value"

        macros.add_macro_definition(test_input)

        mock_update_macros.assert_called_once_with(
            macros.MACRO_VALUES,
            macros.EPHEMERAL_MACRO_VALUES,
        )

    @patch("monitor.lib.macros.logger")
    def test_add_macro_definition_logs_success(self, mock_logger):
        """Test that add_macro_definition logs successful additions."""
        test_input = "<test_key=test_value"

        macros.add_macro_definition(test_input)

        mock_logger.info.assert_called_once_with(
            "Macro added: {} = {}".format("test_key", "test_value")
        )

    @patch("monitor.lib.macros.logger")
    def test_add_macro_definition_logs_error(self, mock_logger):
        """Test that add_macro_definition logs errors for invalid format."""
        test_input = "<invalid_format"

        macros.add_macro_definition(test_input)

        mock_logger.error.assert_called_once_with(
            "Error in macro formatting. Expected format: '<key=expansion'"
        )

    def test_macro_values_global_dict_exists(self):
        """Test that MACRO_VALUES global dictionary exists and is modifiable."""
        self.assertIsInstance(macros.MACRO_VALUES, dict)

        # Test that we can modify it
        test_key = "test_global_macro"
        test_value = "test_global_value"
        macros.MACRO_VALUES[test_key] = test_value

        self.assertEqual(macros.MACRO_VALUES[test_key], test_value)

    def test_macro_file_path_exists(self):
        """Test that MACRO_FILE_PATH is defined."""
        with patch("monitor.config.MACRO_FILE_PATH", "/dummy/path/for/test"):
            import monitor.config

            self.assertIsNotNone(monitor.config.MACRO_FILE_PATH)
            self.assertIsInstance(monitor.config.MACRO_FILE_PATH, (str, type(None)))

    def test_macro_constants_imported(self):
        """Test that macro delimiter constants are imported."""
        # These should be imported from monitor.config
        self.assertTrue(hasattr(config, "MACRO_DELIMITER_OPEN"))
        self.assertTrue(hasattr(config, "MACRO_DELIMITER_CLOSE"))
        self.assertTrue(hasattr(config, "MACRO_DELIMITER_ESCAPE"))

    def test_logger_configured(self):
        """Test that logger is properly configured."""
        self.assertIsNotNone(macros.logger)
        self.assertEqual(macros.logger.name, "monitor.lib.macros")

    def test_integration_configure_and_add_macro(self):
        """Integration test: configure macros then add a new one."""
        # Clear and configure macros
        macros.MACRO_VALUES.clear()

        with patch("monitor.lib.macros.load_additional_macros", return_value={}):
            macros.configure_macros()

        # Add a new macro
        test_input = "<integration_test=success"
        result = macros.add_macro_definition(test_input)

        self.assertTrue(result)
        self.assertIn("integration_test", macros.EPHEMERAL_MACRO_VALUES)
        self.assertIn("integration_test", macros.MACRO_VALUES)

    def test_macro_values_structure_consistency(self):
        """Test that all macro value dictionaries contain only string values."""
        for macro_dict in [
            macros.EPHEMERAL_MACRO_VALUES,
            macros.PRIVATE_MACRO_VALUES,
            macros.PUBLIC_MACRO_VALUES,
        ]:
            for key, value in macro_dict.items():
                self.assertIsInstance(key, str, f"Key {key} should be string")
                self.assertIsInstance(value, str, f"Value for key {key} should be string")

    @patch("monitor.lib.macros.logger")
    @patch("builtins.print")
    @patch("os.environ.get")
    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("subprocess.run")
    @patch("os.path.dirname")
    def test_open_macros_editor_with_editor_env(
        self,
        mock_dirname,
        mock_run,
        mock_makedirs,
        mock_exists,
        mock_environ_get,
        mock_print,
        mock_logger,
    ):
        """Test open_macros_editor uses $EDITOR when set."""
        mock_environ_get.return_value = "customeditor"
        mock_dirname.return_value = "/etc"
        mock_exists.return_value = True
        test_path = "/etc/macros.json"
        with patch.object(config, "MACRO_FILE_PATH", test_path):
            macros.open_macros_editor()
        self.assertEqual(mock_environ_get.call_count, 1)
        mock_run.assert_called_once_with(["customeditor", test_path], check=True)
        mock_print.assert_any_call("Opening macros file in: customeditor")
        self.assertFalse(mock_logger.error.called)
        self.assertFalse(mock_makedirs.called)

    @patch("monitor.lib.macros.logger")
    @patch("builtins.print")
    @patch("os.environ.get")
    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("subprocess.run", side_effect=[FileNotFoundError, None])
    @patch("os.path.dirname")
    def test_open_macros_editor_fallback_to_nano(
        self,
        mock_dirname,
        mock_run,
        mock_makedirs,
        mock_exists,
        mock_environ_get,
        mock_print,
        mock_logger,
    ):
        """Test open_macros_editor falls back to nano, then vim, then vi."""
        test_path = "/fake/path/macros.json"
        # $EDITOR not set
        mock_environ_get.return_value = None
        mock_dirname.return_value = "/fake/path"
        mock_exists.side_effect = lambda p: True
        editors_tried = []

        # Patch subprocess.run to fail first (vim), succeed second time (nano)
        def subprocess_run_side_effect(args, check):
            editors_tried.append(args[0])
            if args[0] == "vim":
                raise FileNotFoundError()
            # Success on vim
            return None

        mock_run.side_effect = subprocess_run_side_effect
        with patch.object(config, "MACRO_FILE_PATH", test_path):
            macros.open_macros_editor()
        self.assertEqual(editors_tried, ["vim", "nano"])
        mock_print.assert_any_call("Opening macros file in: nano")
        mock_print.assert_any_call("Opening macros file in: vim")
        self.assertFalse(mock_logger.error.called)
        self.assertFalse(mock_makedirs.called)

    @patch("monitor.lib.macros.logger")
    @patch("builtins.print")
    @patch("os.environ.get")
    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("subprocess.run", side_effect=FileNotFoundError)
    @patch("os.path.dirname")
    def test_open_macros_editor_error_when_no_editor_found(
        self,
        mock_dirname,
        mock_run,
        mock_makedirs,
        mock_exists,
        mock_environ_get,
        mock_print,
        mock_logger,
    ):
        """Test open_macros_editor prints/logs error if no suitable editor is found."""
        # $EDITOR not set
        mock_environ_get.return_value = None
        mock_dirname.return_value = "/nowhere"
        mock_exists.return_value = True
        test_path = "/nowhere/macros.json"
        with patch.object(config, "MACRO_FILE_PATH", test_path):
            macros.open_macros_editor()
        # Should try nano, vim, vi and fail all; one call for each
        self.assertEqual(mock_run.call_count, 3)
        mock_logger.error.assert_any_call(
            "Could not find a suitable editor (tried nano, vim, vi). Please set the $EDITOR environment variable."
        )

    @patch("monitor.lib.macros.logger")
    @patch("builtins.print")
    @patch("os.environ.get")
    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("subprocess.run")
    @patch("os.path.dirname")
    def test_open_macros_editor_creates_macro_file_path_if_missing(
        self,
        mock_dirname,
        mock_run,
        mock_makedirs,
        mock_exists,
        mock_environ_get,
        mock_print,
        mock_logger,
    ):
        """Test open_macros_editor creates MACRO_FILE_PATH dir if missing."""
        mock_environ_get.return_value = "vim"
        test_dir = "/should/make"
        test_path = test_dir + "/macros.json"

        # Directory does not exist at first
        def exists_side_effect(path):
            if path == test_dir:
                return False
            return True

        mock_exists.side_effect = exists_side_effect
        mock_dirname.return_value = test_dir
        with patch.object(config, "MACRO_FILE_PATH", test_path):
            macros.open_macros_editor()
        mock_makedirs.assert_called_once_with(test_dir, exist_ok=True)
        mock_run.assert_called_once_with(["vim", test_path], check=True)


if __name__ == "__main__":
    unittest.main()
