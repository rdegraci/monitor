import logging
import os
import shlex
import subprocess
import tempfile

import litellm

from monitor import config
from monitor.lib.colors import reset, yellow
from monitor.lib.commit_analyzer import build_commit_message_query_input
from monitor.lib.git import perform_git_commit, perform_git_diff_staged
from monitor.lib.macros import MACRO_VALUES
from monitor.lib.progress import progress_dots

logger = logging.getLogger("monitor.core.commit")


def get_staged_diff(silent: bool = False):
    """
    Return the staged git diff as a string.

    Parameters:
        silent (bool): If True, suppresses user-facing output from the underlying
            git wrapper. This value is passed through to perform_git_diff_staged.

    Uses the centralized git wrapper perform_git_diff_staged(silent=silent).
    """
    logger.debug(
        "Entering get_staged_diff to retrieve staged git diff via perform_git_diff_staged."
    )
    try:
        diff = perform_git_diff_staged(silent=silent)
        logger.debug("Successfully retrieved staged git diff via wrapper.")
        return diff
    except Exception as e:
        logger.error(
            f"Error getting staged diff via perform_git_diff_staged: {e}",
            exc_info=True,
        )
        raise


def _get_commit_generation_config():
    """Return commit-specific LLM configuration with global fallbacks.

    Returns:
        dict[str, object]: A dict containing the model, reasoning effort, and
        reasoning token cap to use for commit message generation.
    """
    model = getattr(config, "COMMIT_MODEL", None) or config.MODEL
    effort = (
        getattr(config, "COMMIT_REASONING_EFFORT", None)
        or getattr(config, "REASONING_EFFORT", None)
    )
    token_cap = (
        getattr(config, "COMMIT_REASONING_MAX_COMPLETION_TOKENS", None)
        or getattr(config, "REASONING_MAX_COMPLETION_TOKENS", None)
    )
    return {
        "model": model,
        "reasoning_effort": effort,
        "reasoning_max_completion_tokens": token_cap,
    }


def _build_commit_completion_kwargs(
    model, reasoning_effort, reasoning_max_completion_tokens
):
    """Build keyword arguments for commit message generation.

    Args:
        model: The model name to use for the completion.
        reasoning_effort: Optional reasoning effort value for reasoning models.
        reasoning_max_completion_tokens: Optional token cap for reasoning models.

    Returns:
        dict[str, object]: Arguments suitable for ``litellm.completion``.
    """
    kwargs = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You write clear, conventional git commit messages.",
            },
        ],
    }
    if _should_use_reasoning_kwargs(model):
        if isinstance(reasoning_effort, str) and reasoning_effort.strip():
            kwargs["reasoning_effort"] = reasoning_effort.strip()
        if (
            isinstance(reasoning_max_completion_tokens, int)
            and reasoning_max_completion_tokens > 0
        ):
            kwargs["max_completion_tokens"] = reasoning_max_completion_tokens
    return kwargs


def _should_use_reasoning_kwargs(model):
    """Return whether the commit model should receive reasoning parameters."""
    prefix = getattr(config, "REASONING_MODEL_PREFIX", None)
    return (
        isinstance(prefix, str)
        and prefix
        and isinstance(model, str)
        and model.lower().startswith(prefix.lower())
    )


def make_commit_command(arg=None, print_func=print):
    """
    Orchestrate the interactive commit flow for :make_commit built-in.
    Shows a diff, generates message, allows edit, and commits.
    Uses centralized git wrapper perform_git_commit.
    """
    logger.info(f"Starting make_commit_command with arg={arg!r}")
    try:
        diff_output = get_staged_diff(silent=True)
        if not diff_output.strip():
            logger.info("No staged changes found. Aborting commit flow.")
            print_func(
                f"{yellow}No staged changes to commit. Please stage changes first.{reset}"
            )
            return

        logger.info("Requesting suggested commit message for staged changes.")
        try:
            commit_message = get_suggested_commit_message(diff_output)
        except KeyboardInterrupt:
            print_func("\nCommit message generation cancelled. Nothing committed.")
            return
        except Exception as e:
            logger.error("Commit message generation failed: %s", e, exc_info=True)
            print_func(
                f"{yellow}Couldn't generate a commit message: {e}{reset}\n"
                "Your staged changes are untouched — try again, or commit manually."
            )
            return
        logger.info("Received suggested commit message.")
        print_func(
            f"\n\n\nSuggested commit message:\n\n{yellow}{commit_message}{reset}\n\n"
        )

        resp = (
            input(
                "Use this commit message? [y/yes] to accept, [e/edit] to edit, [n/no] to abort: "
            )
            .strip()
            .lower()
        )
        if resp in ("e", "edit"):
            logger.info(
                "User selected 'Edit'. Opening editor for commit message editing."
            )
            tf = tempfile.NamedTemporaryFile(
                delete=False, mode="w+t", suffix=".COMMIT_EDITMSG", encoding="utf-8"
            )
            try:
                tf.write(commit_message)
                tf.flush()
                tf.close()
                editor = os.environ.get("EDITOR", "vim")
                try:
                    proc = subprocess.run(shlex.split(editor) + [tf.name])
                except FileNotFoundError:
                    logger.error("Editor %r not found. Aborting commit.", editor)
                    print_func(f"Editor '{editor}' not found. Aborting.")
                    return
                except Exception as ex:
                    logger.error(f"Could not open editor: {ex}. Aborting.", exc_info=True)
                    print_func(f"Could not open editor: {ex}\nAborting.")
                    return
                if proc.returncode != 0:
                    logger.info(
                        "Editor exited with status %d. Aborting commit.", proc.returncode
                    )
                    print_func(
                        f"Editor exited with non-zero status {proc.returncode}. Aborting."
                    )
                    return
                with open(tf.name, "r", encoding="utf-8") as f:
                    final_message = f.read().strip()
                logger.debug("Edited commit message loaded from temporary file.")
            finally:
                try:
                    os.unlink(tf.name)
                except OSError:
                    pass
        elif resp in ("y", "yes"):
            final_message = commit_message
        else:
            logger.info("User selected 'No/Abort'. Aborting commit.")
            print_func("Aborting commit.")
            return

        if not final_message.strip():
            logger.info("Final commit message is empty after edit. Aborting.")
            print_func("Commit message cannot be empty. Aborting.")
            return

        logger.info(
            "Attempting to commit staged changes with the composed commit message via perform_git_commit."
        )
        try:
            perform_git_commit(final_message)
            logger.info("Git commit succeeded via perform_git_commit.")
        except Exception as e:
            logger.error(f"Git commit failed via perform_git_commit: {e}", exc_info=True)
            print_func(f"Git commit failed: {e}")
            return

        print_func(f"{yellow}✅ Commit created successfully.{reset}")
        logger.info("Commit created successfully.")
    except Exception as e:
        logger.error(f"Error in :make_commit: {e}", exc_info=True)
        print_func(f"Error in :make_commit: {e}")


def get_suggested_commit_message(diff_output):
    """
    Return a suggested commit message based on staged git changes.

    Uses a stateless ``litellm.completion`` call rather than ``query()`` so the
    diff and the generated message are NOT appended to the live conversation
    history — generating a commit message shouldn't pollute the model's context
    or token/cost accounting for subsequent turns.
    """
    logger.debug(
        "Entering get_suggested_commit_message to generate message from staged changes."
    )
    try:
        query_input = build_commit_message_query_input(
            diff=diff_output,
            macro_values=MACRO_VALUES,
            macro_delim_open=config.MACRO_DELIMITER_OPEN,
            macro_delim_close=config.MACRO_DELIMITER_CLOSE,
            macro_delim_escape=config.MACRO_DELIMITER_ESCAPE,
        )
        logger.debug("Built commit message query input for staged changes.")
        generation_config = _get_commit_generation_config()
        kwargs = _build_commit_completion_kwargs(
            generation_config["model"],
            generation_config["reasoning_effort"],
            generation_config["reasoning_max_completion_tokens"],
        )
        kwargs["messages"] = [
            {
                "role": "system",
                "content": "You write clear, conventional git commit messages.",
            },
            {"role": "user", "content": query_input},
        ]
        with progress_dots("Generating commit message"):
            response = litellm.completion(**kwargs)
        logger.debug("Generated suggested commit message.")
        return response.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"Error generating suggested commit message: {e}", exc_info=True)
        raise
