
import os
import tempfile
import sys
import logging

from monitor import config 

from monitor.lib.macros import MACRO_VALUES
from monitor.lib.colors import yellow, reset
from monitor.lib.commit_analyzer import build_commit_message_query_input
from monitor.core.conversation import query
from monitor.lib.git import perform_git_commit, perform_git_diff_staged  # Import centralized git wrappers

logger = logging.getLogger('core.commit')

def get_staged_diff():
    """Return the staged git diff as a string. Uses centralized git wrapper perform_git_diff_staged."""
    logger.debug("Entering get_staged_diff to retrieve staged git diff via perform_git_diff_staged.")
    try:
        diff = perform_git_diff_staged()
        logger.debug("Successfully retrieved staged git diff via wrapper.")
        return diff
    except Exception as e:
        logger.error(f"Error getting staged diff via perform_git_diff_staged: {e}", exc_info=True)
        raise

def make_commit_command(arg=None):
    """
    Orchestrate the interactive commit flow for :make_commit built-in.
    Shows a diff, generates message, allows edit, and commits.
    Uses centralized git wrapper perform_git_commit.
    """
    logger.info(f"Starting make_commit_command with arg={arg!r}")
    try:
        diff_output = get_staged_diff()
        if not diff_output.strip():
            logger.info("No staged changes found. Aborting commit flow.")
            print(f"{yellow}No staged changes to commit. Please stage changes first.{reset}")
            return

        # Generate suggested commit message (title, body)
        logger.info("Requesting suggested commit message for staged changes.")
        commit_message = get_suggested_commit_message()
        logger.info("Received suggested commit message.")
        print(f"\n\n\nSuggested commit message:\n\n{yellow}{commit_message}{reset}\n\n")

        resp = input("Use this commit message? [y/yes] to accept, [e/edit] to edit, [n/no] to abort: ").strip().lower()
        if resp in ("e", "edit"):
            logger.info("User selected 'Edit'. Opening editor for commit message editing.")
            with tempfile.NamedTemporaryFile(delete=False, mode="w+t", suffix=".COMMIT_EDITMSG", encoding="utf-8") as tf:
                tf.write(commit_message)
                tf.flush()
                editor = os.environ.get("EDITOR", "vim")
                try:
                    os.system(f"{editor} {tf.name}")
                    logger.debug(f"Editor {editor} launched for commit message editing via os.system.")
                except Exception as ex:
                    logger.error(f"Could not open editor: {ex}. Aborting.", exc_info=True)
                    print(f"Could not open editor: {ex}\nAborting.")
                    return
                tf.seek(0)
                with open(tf.name, "r", encoding="utf-8") as f:
                    edited_msg = f.read().strip()
                os.unlink(tf.name)
                final_message = edited_msg
                logger.debug("Edited commit message loaded from temporary file.")
        elif resp in ("y", "yes"):
            final_message = commit_message
        else:
            logger.info("User selected 'No/Abort'. Aborting commit.")
            print("Aborting commit.")
            return

        if not final_message.strip():
            logger.info("Final commit message is empty after edit. Aborting.")
            print("Commit message cannot be empty. Aborting.")
            return

        # Commit staged changes with the message using perform_git_commit wrapper
        logger.info("Attempting to commit staged changes with the composed commit message via perform_git_commit.")
        try:
            perform_git_commit(final_message)
            logger.info("Git commit succeeded via perform_git_commit.")
        except Exception as e:
            logger.error(f"Git commit failed via perform_git_commit: {e}", exc_info=True)
            print(f"Git commit failed: {e}")
            return

        print(f"{yellow}✅ Commit created successfully.{reset}")
        logger.info("Commit created successfully.")
    except Exception as e:
        logger.error(f"Error in :make_commit: {e}", exc_info=True)
        print(f"Error in :make_commit: {e}")

def get_suggested_commit_message():
    """
    Returns a suggested commit message based on staged git changes.
    """
    logger.debug("Entering get_suggested_commit_message to generate message from staged changes.")
    try:
        query_input = build_commit_message_query_input(
            macro_values=MACRO_VALUES,
            macro_delim_open=config.MACRO_DELIMITER_OPEN,
            macro_delim_close=config.MACRO_DELIMITER_CLOSE,
            macro_delim_escape=config.MACRO_DELIMITER_ESCAPE
        )
        logger.debug("Built commit message query input for staged changes.")
        message = query(query_input)
        logger.debug("Generated suggested commit message.")
        return message
    except Exception as e:
        logger.error(f"Error generating suggested commit message: {e}", exc_info=True)
        raise


