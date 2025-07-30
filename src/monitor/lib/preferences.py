
import os
import subprocess
import shutil
import logging


logger = logging.getLogger(__name__)


def get_preference_editor(config):
    """Determine the preferred editor from environment, config, or fallback.

    Args:
        config (dict): Configuration dictionary.

    Returns:
        str or None: Path to the editor executable, or None if not found.
    """
    editor = (
        os.environ.get("EDITOR") or
        config.get("Editor") or
        config.get("PREFERENCE_EDITOR") or
        '/usr/bin/vi'
    )
    if os.path.isabs(editor):
        if editor == '/usr/bin/vi':
            found = shutil.which(editor)
            if found is not None:
                return found
            is_file = os.path.isfile(editor)
            has_access = os.access(editor, os.X_OK)
            if is_file and has_access:
                return editor
            else:
                logger.error(f"Editor at absolute path '{editor}' is not a file or not executable, and not found in PATH.")
                return None
        else:
            found = shutil.which(editor)
            is_file = os.path.isfile(editor)
            has_access = os.access(editor, os.X_OK)
            if is_file and has_access:
                return editor
            elif found is not None:
                return found
            else:
                logger.error(f"Editor at absolute path '{editor}' is not a file or not executable.")
                return None
    else:
        found = shutil.which(editor)
        if found is None:
            logger.error(f"Editor '{editor}' not found in PATH.")
            return None
        return found


def open_preferences_editor(config, *args, **kwargs):
    """Open the preferences file in the configured text editor for editing.

    Attempts to use the $EDITOR environment variable, a config value
    ('Editor' or 'PREFERENCE_EDITOR'), or falls back to '/usr/bin/vi'.
    Handles errors gracefully and informs the user.

    Args:
        config (dict): Configuration dictionary.
    """
    path = get_preferences_file_path(config)
    try:
        if not os.path.exists(path):
            try:
                open(path, 'a').close()
            except Exception as e:
                print(f"Could not create preferences file at {path}: {e}")
                return
        editor = get_preference_editor(config)
        if editor is None:
            logger.warning("No available text editor found. Set $EDITOR or configure a valid editor.")
            return
        try:
            subprocess.call([editor, path])
        except Exception as e:
            logger.error(f"Failed to launch editor '{editor}': {e}", exc_info=True)
            return
        return(f"Preferences updated at: {path}")
    except Exception as e:
        logger.error(f"Unexpected error in open_preferences_editor: {e}", exc_info=True)

PREFERENCE_PROMPT_FILE=None
def load_user_preferences(path):
    """Read and return the user preferences file content, or empty string if not set.

    Handles IO errors gracefully and does not crash.

    Args:
        config (dict): Configuration dictionary.

    Returns:
        str: Contents of the preferences file, or empty string if not present or error.
    """
    global PREFERENCE_PROMPT_FILE
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                PREFERENCE_PROMPT_FILE = f.read().strip()
    except Exception as e:
        logger.error(f"Could not read preferences file at {path}: {e}", exc_info=True)
    return ""





