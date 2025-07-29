import unittest
from unittest.mock import patch, MagicMock, mock_open, call
import os
import sys
import tempfile
import shutil

# Add the parent directory to the path to import the module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor.lib.preferences import (
    get_preferences_file_path,
    get_preference_editor,
    open_preferences_editor,
    load_user_preferences
)


class TestPreferences(unittest.TestCase):
    """Test cases for preferences module functions."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.test_config = {
            "PREFERENCE_PROMPT_FILE": "/test/path/preferences.prompt",
            "PREFERENCE_EDITOR": "nano",
            "Editor": "vim"
        }
        self.default_config = {}

    def test_get_preferences_file_path_with_config(self):
        """Test get_preferences_file_path returns configured path."""
        result = get_preferences_file_path(self.test_config)
        self.assertEqual(result, "/test/path/preferences.prompt")

    @patch('os.path.expanduser')
    def test_get_preferences_file_path_default(self, mock_expanduser):
        """Test get_preferences_file_path returns default path when not configured."""
        mock_expanduser.return_value = "/home/user/.preferences.prompt"
        
        result = get_preferences_file_path(self.default_config)
        
        mock_expanduser.assert_called_once_with("~/.config/monitor/preferences.prompt")
        self.assertEqual(result, "/home/user/.preferences.prompt")

    @patch.dict(os.environ, {'EDITOR': 'emacs'})
    @patch('shutil.which')
    def test_get_preference_editor_from_env(self, mock_which):
        """Test get_preference_editor uses EDITOR environment variable."""
        mock_which.return_value = "/usr/bin/emacs"
        
        result = get_preference_editor(self.default_config)
        print("shutil.which call count:", mock_which.call_count, "mock_calls:", mock_which.mock_calls)
        print("Result of get_preference_editor:", result)
        
        mock_which.assert_called_once_with("emacs")
        self.assertEqual(result, "/usr/bin/emacs")

    @patch.dict(os.environ, {}, clear=True)
    @patch('shutil.which')
    def test_get_preference_editor_from_config_editor(self, mock_which):
        """Test get_preference_editor uses config Editor field."""
        mock_which.return_value = "/usr/bin/vim"
        
        result = get_preference_editor(self.test_config)
        print("shutil.which call count:", mock_which.call_count, "mock_calls:", mock_which.mock_calls)
        print("Result of get_preference_editor:", result)
        
        mock_which.assert_called_once_with("vim")
        self.assertEqual(result, "/usr/bin/vim")

    @patch.dict(os.environ, {}, clear=True)
    @patch('shutil.which')
    def test_get_preference_editor_from_config_preference_editor(self, mock_which):
        """Test get_preference_editor uses PREFERENCE_EDITOR config field."""
        mock_which.return_value = "/usr/bin/nano"
        config = {"PREFERENCE_EDITOR": "nano"}
        
        result = get_preference_editor(config)
        print("shutil.which call count:", mock_which.call_count, "mock_calls:", mock_which.mock_calls)
        print("Result of get_preference_editor:", result)
        
        mock_which.assert_called_once_with("nano")
        self.assertEqual(result, "/usr/bin/nano")

    @patch.dict(os.environ, {}, clear=True)
    @patch('os.path.isfile')
    @patch('os.access')
    def test_get_preference_editor_absolute_path_valid(self, mock_access, mock_isfile):
        """Test get_preference_editor with valid absolute path."""
        mock_isfile.return_value = True
        mock_access.return_value = True
        config = {"PREFERENCE_EDITOR": "/usr/bin/nano"}
        
        result = get_preference_editor(config)
        print("os.path.isfile call count:", mock_isfile.call_count, "mock_calls:", mock_isfile.mock_calls)
        print("os.access call count:", mock_access.call_count, "mock_calls:", mock_access.mock_calls)
        print("Result of get_preference_editor:", result)
        
        mock_isfile.assert_any_call("/usr/bin/nano")
        mock_access.assert_any_call("/usr/bin/nano", os.X_OK)
        self.assertEqual(result, "/usr/bin/nano")

    @patch.dict(os.environ, {}, clear=True)
    @patch('os.path.isfile')
    @patch('os.access')
    def test_get_preference_editor_absolute_path_invalid(self, mock_access, mock_isfile):
        """Test get_preference_editor with invalid absolute path."""
        mock_isfile.return_value = False
        config = {"PREFERENCE_EDITOR": "/invalid/path/editor"}
        
        result = get_preference_editor(config)
        print("os.path.isfile call count:", mock_isfile.call_count, "mock_calls:", mock_isfile.mock_calls)
        print("os.access call count:", mock_access.call_count, "mock_calls:", mock_access.mock_calls)
        print("Result of get_preference_editor:", result)
        
        mock_isfile.assert_any_call("/invalid/path/editor")
        self.assertIsNone(result)

    @patch.dict(os.environ, {}, clear=True)
    @patch('shutil.which')
    def test_get_preference_editor_fallback_to_vi(self, mock_which):
        """Test get_preference_editor falls back to vi when no config provided."""
        mock_which.return_value = "/usr/bin/vi"
        
        result = get_preference_editor(self.default_config)
        print("shutil.which call count:", mock_which.call_count, "mock_calls:", mock_which.mock_calls)
        print("Result of get_preference_editor:", result)
        
        mock_which.assert_called_once_with("/usr/bin/vi")
        self.assertEqual(result, "/usr/bin/vi")

    @patch.dict(os.environ, {}, clear=True)
    @patch('os.path.isfile', return_value=False)
    @patch('os.access', return_value=False)
    @patch('shutil.which')
    def test_get_preference_editor_not_found(self, mock_which, mock_access, mock_isfile):
        """Test get_preference_editor returns None when editor not found."""
        mock_which.return_value = None
        
        result = get_preference_editor(self.default_config)
        print("shutil.which call count:", mock_which.call_count, "mock_calls:", mock_which.mock_calls)
        print("Result of get_preference_editor:", result)
        
        self.assertIsNone(result)

    @patch('monitor.lib.preferences.get_preferences_file_path')
    @patch('monitor.lib.preferences.get_preference_editor')
    @patch('os.path.exists')
    @patch('subprocess.call')
    def test_open_preferences_editor_success(self, mock_subprocess, mock_exists, 
                                           mock_get_editor, mock_get_path):
        """Test open_preferences_editor successfully opens editor."""
        mock_get_path.return_value = "/test/preferences.prompt"
        mock_get_editor.return_value = "/usr/bin/nano"
        mock_exists.return_value = True
        
        result = open_preferences_editor(self.test_config)
        
        mock_subprocess.assert_called_once_with(["/usr/bin/nano", "/test/preferences.prompt"])
        self.assertEqual(result, "Preferences updated at: /test/preferences.prompt")


    @patch('monitor.lib.preferences.get_preferences_file_path')
    @patch('monitor.lib.preferences.get_preference_editor')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open)
    @patch('subprocess.call')
    def test_open_preferences_editor_creates_file(self, mock_subprocess, mock_file,
                                                mock_exists, mock_get_editor, mock_get_path):
        """Test open_preferences_editor creates file if it doesn't exist."""
        mock_get_path.return_value = "/test/preferences.prompt"
        mock_get_editor.return_value = "/usr/bin/nano"
        mock_exists.return_value = False
        
        result = open_preferences_editor(self.test_config)
        
        mock_file.assert_called_once_with("/test/preferences.prompt", 'a')
        mock_subprocess.assert_called_once_with(["/usr/bin/nano", "/test/preferences.prompt"])
        self.assertEqual(result, "Preferences updated at: /test/preferences.prompt")

    @patch('monitor.lib.preferences.get_preferences_file_path')
    @patch('monitor.lib.preferences.get_preference_editor')
    @patch('os.path.exists')
    @patch('builtins.open', side_effect=PermissionError("Access denied"))
    @patch('builtins.print')
    def test_open_preferences_editor_file_creation_error(self, mock_print, mock_file,
                                                       mock_exists, mock_get_editor, mock_get_path):
        """Test open_preferences_editor handles file creation errors."""
        mock_get_path.return_value = "/test/preferences.prompt"
        mock_get_editor.return_value = "/usr/bin/nano"
        mock_exists.return_value = False
        
        result = open_preferences_editor(self.test_config)
        
        mock_print.assert_called_once_with("Could not create preferences file at /test/preferences.prompt: Access denied")
        self.assertIsNone(result)

    @patch('monitor.lib.preferences.get_preferences_file_path')
    @patch('monitor.lib.preferences.get_preference_editor')
    def test_open_preferences_editor_no_editor_found(self, mock_get_editor, mock_get_path):
        """Test open_preferences_editor handles case when no editor is found."""
        mock_get_path.return_value = "/test/preferences.prompt"
        mock_get_editor.return_value = None
        
        result = open_preferences_editor(self.test_config)
        
        self.assertIsNone(result)

    @patch('monitor.lib.preferences.get_preferences_file_path')
    @patch('monitor.lib.preferences.get_preference_editor')
    @patch('os.path.exists')
    @patch('subprocess.call', side_effect=FileNotFoundError("Editor not found"))
    def test_open_preferences_editor_subprocess_error(self, mock_subprocess, mock_exists,
                                                    mock_get_editor, mock_get_path):
        """Test open_preferences_editor handles subprocess errors."""
        mock_get_path.return_value = "/test/preferences.prompt"
        mock_get_editor.return_value = "/usr/bin/nano"
        mock_exists.return_value = True
        
        result = open_preferences_editor(self.test_config)
        
        self.assertIsNone(result)

    @patch('monitor.lib.preferences.get_preferences_file_path')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data="user preferences content")
    def test_load_user_preferences_success(self, mock_file, mock_exists, mock_get_path):
        """Test load_user_preferences successfully reads preferences file."""
        mock_get_path.return_value = "/test/preferences.prompt"
        mock_exists.return_value = True
        
        result = load_user_preferences(self.test_config)
        
        mock_file.assert_called_once_with("/test/preferences.prompt", 'r')
        self.assertEqual(result, "user preferences content")

    @patch('monitor.lib.preferences.get_preferences_file_path')
    @patch('os.path.exists')
    def test_load_user_preferences_file_not_exists(self, mock_exists, mock_get_path):
        """Test load_user_preferences returns empty string when file doesn't exist."""
        mock_get_path.return_value = "/test/preferences.prompt"
        mock_exists.return_value = False
        
        result = load_user_preferences(self.test_config)
        
        self.assertEqual(result, "")

    @patch('monitor.lib.preferences.get_preferences_file_path')
    @patch('os.path.exists')
    @patch('builtins.open', side_effect=PermissionError("Access denied"))
    def test_load_user_preferences_read_error(self, mock_file, mock_exists, mock_get_path):
        """Test load_user_preferences handles file read errors gracefully."""
        mock_get_path.return_value = "/test/preferences.prompt"
        mock_exists.return_value = True
        
        result = load_user_preferences(self.test_config)
        
        self.assertEqual(result, "")

    @patch('monitor.lib.preferences.get_preferences_file_path')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data="  content with whitespace  \n")
    def test_load_user_preferences_strips_whitespace(self, mock_file, mock_exists, mock_get_path):
        """Test load_user_preferences strips whitespace from content."""
        mock_get_path.return_value = "/test/preferences.prompt"
        mock_exists.return_value = True
        
        result = load_user_preferences(self.test_config)
        
        self.assertEqual(result, "content with whitespace")

    def test_integration_with_real_temp_file(self):
        """Integration test using real temporary file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            pref_file = os.path.join(temp_dir, "test_preferences.prompt")
            config = {"PREFERENCE_PROMPT_FILE": pref_file}
            
            # Test file doesn't exist initially
            result = load_user_preferences(config)
            self.assertEqual(result, "")
            
            # Create file with content
            test_content = "This is a test preference"
            with open(pref_file, 'w') as f:
                f.write(test_content)
            
            # Test reading existing file
            result = load_user_preferences(config)
            self.assertEqual(result, test_content)
            
            # Test path resolution
            path = get_preferences_file_path(config)
            self.assertEqual(path, pref_file)


if __name__ == "__main__":
    unittest.main()
