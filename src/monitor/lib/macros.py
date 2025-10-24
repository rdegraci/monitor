"""Handles macro orchestration, configuration, global macro state, and all CLI/user commands. Calls stateless helpers from macro_utils."""

import json
import logging
import os
import subprocess

from monitor import config

from monitor.lib.macro_utils import load_additional_macros, update_macros
from monitor.lib.colors import red, yellow, reset

MACRO_VALUES = {}

logger = logging.getLogger(__name__)

# When adding macros via '<key=value' the macros are stored in EPHEMERAL_MACRO_VALUES
# and are destroyed when monitor exits. If you want macros to persist, use the
# :edit_macros command 
EPHEMERAL_MACRO_VALUES = {}

# Initialize macro values dictionary with hardcoded values
# These are not visible dumping the macros via the 'macros' built in command.
PRIVATE_MACRO_VALUES = {
    "system?": "Are you awake and operational?",
    "memories?": "What are your memories?",
    "purpose?": "What is your purpose?",
    "self_test": "what is the weather in san diego, ca in F? {{purpose?}} {{memories?}}",
}

# Useful macros, these are visible when dumping macros via the 'macros' built in command.
PUBLIC_MACRO_VALUES = {
    "do_diff": "Examine the files that have been modified, using the perform_git_diff tool",
    "create_git_entry": "Provide a git commit title, with a max of 50 characters and a body that describes the changes. The body should be broken up into paragraphs. If the changes are a fix, use \"Fix <bug description>\" as the title.  If the changes are adding a new feature, use \"Add <feature>\" as the title. If the changes are a refactor, use \"Refactor <component>\" as the title. Display this as plain text with no Markdown formatting. Do not prepend the title with Title: and do not prepend the body with Body: just provide the content. There should be one blank line after the title. The git commit body will be read by a tool to analyze Git commits within a branch and builds a contextual understanding of what is happening in the development process, therefore the body should provide comprehensive context",
    "rank_examine": "Rank what to examine next",
    "diff": "{{do_diff}} {{create_git_entry}}",
    "diff_previous": "Examine the files that have been modified since the last commit, using the perform_git_diff_previous tool, so that I can see the difference between the current commit and its parent previous commit. Tell me the results of the overall change.",
    "xdiff": "Use the git show tool to examine the source code changes for the following hash or branch name: ",
    "plan": "Give me a step by step plan",
    "wdyt": "Don't change any code. Tell me what do you think",
}

def configure_macros():
    """Load, update, and configure all macro dictionaries into global MACRO_VALUES.

    Loads additional macros from a file using macro_utils and combines them in
    the correct precedence order: built-ins first (ephemeral, public), then file-based,
    then private. The global MACRO_VALUES will be updated in-place.

    Returns:
        None
    """
    additional_macros = load_additional_macros(config.MACRO_FILE_PATH)
    update_macros(MACRO_VALUES, EPHEMERAL_MACRO_VALUES)
    update_macros(MACRO_VALUES, PUBLIC_MACRO_VALUES)
    update_macros(MACRO_VALUES, additional_macros)
    update_macros(MACRO_VALUES, PRIVATE_MACRO_VALUES)


def print_macros(arg=None):
    """Display the current macro dictionaries using a paginated view.

    Formats both public and ephemeral macro dictionaries as JSON and displays them
    to the user. Pipes through a pager (Unix less-like) if available, falls back
    to print.

    Args:
        arg: Optional; Unused, maintained for CLI handler compatibility.

    Returns:
        None
    """
    macros = load_additional_macros(config.MACRO_FILE_PATH)
    output_parts = [
        json.dumps(PUBLIC_MACRO_VALUES, indent=4, sort_keys=True),
        json.dumps(macros, indent=4, sort_keys=True),
        json.dumps(EPHEMERAL_MACRO_VALUES, indent=4, sort_keys=True),
    ]
    combined_output = "\n\n".join(output_parts)

    try:
        import pydoc

        pydoc.pager(combined_output)
    except Exception as exc:  # pragma: no cover
        print(combined_output)
        logger.warning("pydoc.pager failed: %s; falling back to print.", exc)


def add_macro_definition(user_input):
    """Handles addition of ephemeral macros at runtime via user input.

    Updates the ephemeral macros dictionary and global MACRO_VALUES in-place to include
    new macro definition.

    Args:
        user_input (str): User input string in the form '<key=expansion'

    Returns:
        bool: True if addition succeeded, False if parsing failed.
    """
    try:
        key, value = user_input[1:].split("=", 1)
        key, value = key.strip(), value.strip()
        EPHEMERAL_MACRO_VALUES[key] = value
        update_macros(MACRO_VALUES, EPHEMERAL_MACRO_VALUES)
        print(f"{yellow}Added to macro_values: '{key}': '{value}'{reset}\n")
        logger.info("Macro added: {} = {}".format(key, value))
        return True
    except ValueError:
        logger.error(
            "Error in macro formatting. Expected format: '<key=expansion'"
        )
        return False


def open_macros_editor():
    """Open the user's editor to edit the macros file specified by config.MACRO_FILE_PATH.

    Launches the editor specified by the $EDITOR environment variable or falls back to 'nano' or 'vi'
    to allow the user to edit the macro file directly. If the macro file does not exist, it is created
    as an empty file before launching the editor.

    Returns:
        None

    Raises:
        OSError: If there is a problem launching the editor or saving the file.
    """
    macros_file_path = config.MACRO_FILE_PATH

    try:
        # Ensure parent directory exists before creating or editing the file
        parent_dir = os.path.dirname(macros_file_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        # Create the file if it does not exist
        if not os.path.exists(macros_file_path):
            with open(macros_file_path, "a", encoding="utf-8"):
                pass  # Create empty file

        editor = os.environ.get("EDITOR")
        editors_tried = []
        if editor:
            editors_to_try = [editor]
        else:
            editors_to_try = ["vim", "nano", "vi"]

        for candidate in editors_to_try:
            try:
                print(f"Opening macros file in: {candidate}")
                subprocess.run([candidate, macros_file_path], check=True)
                print(f"{yellow}Macros edited successfully. Reload macros with ':reload_macros' or restart the app to apply changes.{reset}")
                return
            except FileNotFoundError:
                editors_tried.append(candidate)
                continue
            except Exception as exc:
                error_msg = f"{red}Failed to open macros file with {candidate}: {exc}{reset}"
                print(error_msg)
                logger.error(error_msg, exc_info=True)
                editors_tried.append(candidate)
                continue

        # All editors failed, print and log error message as required before raising
        editors_to_report = editors_to_try if editors_tried == editors_to_try else editors_tried
        editor_list_str = 'nano, vim, vi'
        error_msg = f"Could not find a suitable editor (tried {editor_list_str}). Please set the $EDITOR environment variable."
        print(f"{red}{error_msg}{reset}")
        logger.error(error_msg)
        raise OSError(f"No suitable editor found or failed to launch after trying: {', '.join(editors_tried)}. Please set the $EDITOR environment variable.")
    except Exception as exc:
        error_msg = f"{red}Failed to open macros file for editing: {exc}{reset}"
        print(error_msg)
        logger.error(error_msg, exc_info=True)
