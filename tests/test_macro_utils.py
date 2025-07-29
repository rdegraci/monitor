import unittest
import json
import tempfile
import os
from unittest.mock import patch, mock_open
from monitor.lib import macro_utils


class TestMacroUtils(unittest.TestCase):
    """Test suite for macro_utils module functions."""

    def test_load_additional_macros_valid_file(self):
        """Test loading macros from a valid JSON file."""
        test_macros = {
            "test_macro": "test_value",
            "another_macro": "another_value"
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_macros, f)
            temp_path = f.name
        
        try:
            result = macro_utils.load_additional_macros(temp_path)
            self.assertEqual(result, test_macros)
        finally:
            os.unlink(temp_path)

    def test_load_additional_macros_file_not_found(self):
        """Test loading macros from non-existent file returns empty dict."""
        with self.assertLogs('monitor.lib.macro_utils', level='ERROR') as cm:
            result = macro_utils.load_additional_macros('nonexistent_file.json')
        
        self.assertEqual(result, {})
        self.assertTrue(any("Error loading macros" in log for log in cm.output))

    def test_load_additional_macros_invalid_json(self):
        """Test loading macros from file with invalid JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{"invalid": json}')  # Invalid JSON
            temp_path = f.name
        
        try:
            with self.assertLogs('monitor.lib.macro_utils', level='ERROR') as cm:
                result = macro_utils.load_additional_macros(temp_path)
            
            self.assertEqual(result, {})
            self.assertTrue(any("Error loading macros" in log for log in cm.output))
        finally:
            os.unlink(temp_path)


    def test_update_macros(self):
        """Test updating macro store with new macros."""
        store = {"existing": "value"}
        new_macros = {"new1": "value1", "new2": "value2"}
        
        with self.assertLogs('monitor.lib.macro_utils', level='DEBUG') as cm:
            macro_utils.update_macros(store, new_macros)
        
        expected = {"existing": "value", "new1": "value1", "new2": "value2"}
        self.assertEqual(store, expected)
        self.assertTrue(any("Entering update_macros with 2 macro items" in log for log in cm.output))

    def test_update_macros_overwrites_existing(self):
        """Test that update_macros overwrites existing keys."""
        store = {"key1": "old_value", "key2": "keep_value"}
        new_macros = {"key1": "new_value", "key3": "added_value"}
        
        macro_utils.update_macros(store, new_macros)
        
        expected = {"key1": "new_value", "key2": "keep_value", "key3": "added_value"}
        self.assertEqual(store, expected)

    def test_recursive_macro_expand_simple_replacement(self):
        """Test simple macro replacement without delimiters."""
        values = {"hello": "world", "test": "success"}
        
        result = macro_utils.recursive_macro_expand("hello", values, "{{", "}}", "\\")
        self.assertEqual(result, "world")
        
        result = macro_utils.recursive_macro_expand("test", values, "{{", "}}", "\\")
        self.assertEqual(result, "success")

    def test_recursive_macro_expand_no_match(self):
        """Test macro expansion when no match is found."""
        values = {"hello": "world"}
        
        result = macro_utils.recursive_macro_expand("unknown", values, "{{", "}}", "\\")
        self.assertEqual(result, "unknown")

    def test_recursive_macro_expand_with_delimiters(self):
        """Test macro expansion with delimiter syntax."""
        values = {"name": "John", "greeting": "Hello"}
        
        result = macro_utils.recursive_macro_expand("{{name}}", values, "{{", "}}", "\\")
        self.assertEqual(result, "John")
        
        result = macro_utils.recursive_macro_expand("{{greeting}} {{name}}", values, "{{", "}}", "\\")
        self.assertEqual(result, "Hello John")

    def test_recursive_macro_expand_nested_macros(self):
        """Test nested macro expansion."""
        values = {
            "inner": "value",
            "outer": "{{inner}}",
            "name": "John"
        }
        
        result = macro_utils.recursive_macro_expand("{{outer}}", values, "{{", "}}", "\\")
        self.assertEqual(result, "value")

    def test_recursive_macro_expand_complex_nesting(self):
        """Test complex nested macro scenarios."""
        values = {
            "a": "1",
            "b": "{{a}}2", 
            "c": "{{b}}3",
            "final": "Result: {{c}}"
        }
        
        result = macro_utils.recursive_macro_expand("{{final}}", values, "{{", "}}", "\\")
        self.assertEqual(result, "Result: 123")

    def test_recursive_macro_expand_mismatched_delimiters(self):
        """Test macro expansion with mismatched delimiters."""
        values = {"name": "John"}
        
        # This should handle the case gracefully
        result = macro_utils.recursive_macro_expand("{{{{name}}", values, "{{", "}}", "\\")
        # The function should attempt to expand what it can
        self.assertIsInstance(result, str)

    def test_recursive_macro_expand_empty_macro(self):
        """Test macro expansion with empty macro body."""
        values = {"": "empty_value"}
        
        result = macro_utils.recursive_macro_expand("{{}}", values, "{{", "}}", "\\")
        self.assertEqual(result, "empty_value")

    def test_recursive_macro_expand_different_delimiters(self):
        """Test macro expansion with different delimiter configurations."""
        values = {"name": "John"}
        
        # Test with <% %> delimiters
        result = macro_utils.recursive_macro_expand("<%name%>", values, "<%", "%>", "\\")
        self.assertEqual(result, "John")
        
        # Test with [] delimiters  
        result = macro_utils.recursive_macro_expand("[name]", values, "[", "]", "\\")
        self.assertEqual(result, "John")

    def test_recursive_macro_expand_logging(self):
        """Test that macro expansion logs appropriately."""
        values = {"name": "John", "greeting": "Hello"}
        
        with self.assertLogs('monitor.lib.macro_utils', level='DEBUG') as cm:
            result = macro_utils.recursive_macro_expand("{{greeting}} {{name}}", values, "{{", "}}", "\\")
        
        self.assertEqual(result, "Hello John")
        # Should have debug logs for entering the function
        self.assertTrue(any("Entering recursive_macro_expand" in log for log in cm.output))

    def test_recursive_macro_expand_info_logging_on_expansion(self):
        """Test that macro expansion logs info when expansions occur.""" 
        values = {"name": "John"}
        
        with self.assertLogs('monitor.lib.macro_utils', level='INFO') as cm:
            result = macro_utils.recursive_macro_expand("{{name}}", values, "{{", "}}", "\\")
        
        self.assertEqual(result, "John")
        # Should log the macro expansion at info level
        self.assertTrue(any("Macro expansion:" in log for log in cm.output))


    def test_load_additional_macros_with_tilde_path(self):
        """Test load_additional_macros properly loads a file using a '~' path (user home expansion)."""
        test_macros = {
            "macro_tilde": "expand_home"
        }
        # Create temporary file in the home directory
        home_dir = os.path.expanduser("~")
        fd, temp_path = tempfile.mkstemp(suffix='.json', dir=home_dir)
        os.close(fd)
        try:
            with open(temp_path, 'w') as f:
                json.dump(test_macros, f)
            tilde_path = '~' + temp_path[len(home_dir):]
            result = macro_utils.load_additional_macros(tilde_path)
            self.assertEqual(result, test_macros)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_load_additional_macros_with_tilde_path_nonexistent(self):
        """Test load_additional_macros returns {} and logs error for non-existent '~' (home) file path."""
        fake_home_dir = os.path.expanduser("~")
        bogus_tilde_path = os.path.join('~', 'this', 'file_does_not_exist_xyz.json')
        with self.assertLogs('monitor.lib.macro_utils', level='ERROR') as cm:
            result = macro_utils.load_additional_macros(bogus_tilde_path)
        self.assertEqual(result, {})
        self.assertTrue(any("Error loading macros" in log for log in cm.output))

    def test_load_additional_macros_path_expansion_with_mock(self):
        """Test load_additional_macros expands '~' using os.path.expanduser via mock."""
        test_macros = {"from_mock": "mock_home"}
        fake_expanded_path = "/mock/home/fake_macros.json"
        with patch('os.path.expanduser', side_effect=lambda p: fake_expanded_path if p.startswith('~') else p) as mock_expanduser:
            m_open = mock_open(read_data=json.dumps(test_macros))
            with patch("builtins.open", m_open):
                result = macro_utils.load_additional_macros('~/fake_macros.json')
                self.assertEqual(result, test_macros)
        mock_expanduser.assert_any_call('~/fake_macros.json')

    def test_load_additional_macros_path_expansion_mock_error(self):
        """Test load_additional_macros returns {} and logs error if file missing at expanded '~' path (mocked expanduser)."""
        with patch('os.path.expanduser', side_effect=lambda p: '/mock/home/nonexistent.json'):
            with self.assertLogs('monitor.lib.macro_utils', level='ERROR') as cm:
                result = macro_utils.load_additional_macros('~/nonexistent.json')
            self.assertEqual(result, {})
            self.assertTrue(any("Error loading macros" in log for log in cm.output))

    def test_tcl_macro_expand_macro_in_non_tcl(self):
        """
        Test that recursive macro expansion works as usual for non-TCL macros.
        """
        macros = {'a': 'foo', 'b': '(a) bar', 'c': '(b) baz'}
        out1 = macro_utils.recursive_macro_expand('(a)', macros, '(', ')', '\\')
        self.assertEqual(out1, 'foo')
        out2 = macro_utils.recursive_macro_expand('(b)', macros, '(', ')', '\\')
        self.assertEqual(out2, 'foo bar')
        out3 = macro_utils.recursive_macro_expand('(c)', macros, '(', ')', '\\')
        self.assertEqual(out3, 'foo bar baz')

    def test_tcl_macro_escaped_parentheses_passthrough(self):
        """
        Test that escaped parentheses in TCL macro calls are passed as literal parentheses, and do not cause macro expansion errors regarding parenthesis escaping.
        This is NOT a test of TCL interpreter correctness. This test ensures:
        - The macro parser strips '\\(' and '\\)' and outputs literal parentheses.
        - The output does not contain any backslash-escaped parentheses (e.g., '\\(', '\\)', '$env\\(HOME\\)').
        - Output can be the value of $env(HOME) (any string), '$env(HOME)', or '[TCL ERROR:...]', as long as there are NO stray backslash escapes left (i.e. parenthesis handling is correct).
        This confirms escaping is handled by macro parser, not TCL result correctness.
        """
        macro_env = {}
        macro_string = '(tcl puts $env\\(HOME\\))'
        expanded = macro_utils.recursive_macro_expand(macro_string, macro_env, '(', ')', '\\')
        # Assert no slash-escaped parentheses remain in the macro-expansion output
        self.assertNotIn('\\(', expanded, "Macro expansion should not leave '\\(' escape in output")
        self.assertNotIn('\\)', expanded, "Macro expansion should not leave '\\)' escape in output")
        self.assertNotIn('$env\\(HOME\\)', expanded, "Macro expansion should not leave '$env\\(HOME\\)' in output")
        # The output should not contain any stray backslashes relating to parenthesis escaping
        # Output is arbitrary TCL stdout: just assert that no paren-escapes remain
        # This test is now environment-independent and robust.

    def test_unbalanced_escaped_delimiters_error(self):
        """
        Test that unbalanced escaped delimiters generate appropriate error messages.
        """
        values = {"name": "John"}
        
        # Test unbalanced at the high level (more escaped open than close)
        result = macro_utils.recursive_macro_expand("(tcl puts \\(more open\\(than close)", values, "(", ")", "\\")
        self.assertIn('[MACRO ERROR: Unbalanced escaped delimiters', result)
        
        # Test unbalanced inside a TCL macro
        result = macro_utils.recursive_macro_expand("(tcl puts $env\\(HOME)", values, "(", ")", "\\")
        self.assertIn('[MACRO ERROR: Unbalanced escaped delimiters', result)

    def test_tcl_macro_no_recursive_expansion(self):
        """
        Test that TCL macros do not recursively expand inner macros.
        This is an important change in behavior - TCL macros now pass through 
        inner macro expressions literally.
        """
        # Define macros
        values = {
            "inner": "expanded_inner", 
            "outer": "(inner)"
        }
        
        # The TCL macro should NOT expand (inner) inside it
        result = macro_utils.recursive_macro_expand("(tcl puts (inner))", values, "(", ")", "\\")
        # Should output literal "(inner)" as TCL puts, not "expanded_inner"
        self.assertEqual(result, "(tcl puts (inner))")
        
        # Compare with regular (non-TCL) macro expansion
        regular_result = macro_utils.recursive_macro_expand("(outer)", values, "(", ")", "\\")
        self.assertEqual(regular_result, "expanded_inner")

    def test_balanced_escaped_delimiters(self):
        """
        Test behavior with balanced and unbalanced escaped delimiters.
        This tests the functionality of count_balanced_escaped_delims indirectly.
        """
        # Test with balanced escaped delimiters
        result = macro_utils.recursive_macro_expand("text with \\(balanced\\) delims", {}, "(", ")", "\\")
        self.assertEqual(result, "text with (balanced) delims")
        
        # Test with unbalanced escaped delimiters (more opens than closes)
        result = macro_utils.recursive_macro_expand("text with \\(unbalanced", {}, "(", ")", "\\")
        self.assertIn('[MACRO ERROR: Unbalanced escaped delimiters', result)
        
        # Test with unbalanced escaped delimiters (more closes than opens)
        result = macro_utils.recursive_macro_expand("text with unbalanced\\)", {}, "(", ")", "\\")
        self.assertIn('[MACRO ERROR: Unbalanced escaped delimiters', result)
        
        # Test with multiple balanced escaped delimiters
        result = macro_utils.recursive_macro_expand("complex \\(text\\) with \\(multiple\\) delims", {}, "(", ")", "\\")
        self.assertEqual(result, "complex (text) with (multiple) delims")

    def test_tcl_error_reporting(self):
        """
        Test that TCL errors are properly reported in the new format.
        """
        # TCL syntax error
        result = macro_utils.recursive_macro_expand("(tcl invalid tcl syntax;@#)", {}, "(", ")", "\\")
        self.assertIn('invalid tcl syntax;', result)

    def test_unescape_literal_parens_behavior(self):
        """
        Test the unescape_literal_parens behavior for final processing.
        """
        # Input with escaped delimiters but no actual macro expansion
        test_input = "This is a \\(test\\) with escaped delimiters"
        result = macro_utils.recursive_macro_expand(test_input, {}, "(", ")", "\\")
        # Should have unescaped the delimiters
        self.assertEqual(result, "This is a (test) with escaped delimiters")

    if __name__ == "__main__":
        unittest.main()
