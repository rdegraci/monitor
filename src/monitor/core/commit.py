import logging
import os
import re
import shlex
import subprocess
import tempfile
from textwrap import TextWrapper, dedent

from monitor import config
from monitor.lib.colors import reset, yellow
from monitor.lib.commit_analyzer import build_commit_message_query_input
from monitor.lib.git import perform_git_commit, perform_git_diff_staged
from monitor.lib.llm_utils import (
    call_litellm_completion,
    is_reasoning_model,
    log_helper_model_usage,
)
from monitor.lib.macros import MACRO_VALUES
from monitor.lib.progress import progress_dots

logger = logging.getLogger("monitor.core.commit")

COMMIT_BODY_MAX_LINE_LENGTH = 72
_URL_IN_LINE_RE = re.compile(r"https?://\S+", re.IGNORECASE)
# Cap ordered markers at 3 digits so years like "2024. …" stay wrap-eligible prose.
_LIST_ITEM_RE = re.compile(r"^(?:[-*+]|\d{1,3}\.)\s+")
# CommonMark-ish fences: backticks or tildes, at most 3 leading spaces;
# closing fences have no info string and must reuse the opening character.
_CODE_FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")


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
    logger.info(
        "Resolved commit config: model=%r reasoning_effort=%r reasoning_max_completion_tokens=%r",
        model,
        effort,
        token_cap,
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
    """Return whether the commit model should receive reasoning parameters.

    Args:
        model: The candidate model name.

    Returns:
        bool: True when the model should receive reasoning-specific kwargs.
    """
    return is_reasoning_model(model, getattr(config, "REASONING_MODEL_PREFIX", None))


def _extract_commit_body(message):
    """Return the text after the first blank line in a commit message.

    Args:
        message: Full commit message text.

    Returns:
        str: Body text, or an empty string when the message has no body section.
    """
    if not isinstance(message, str) or not message.strip():
        return ""
    parts = message.strip().split("\n\n", 1)
    if len(parts) < 2:
        return ""
    return parts[1]


def _line_contains_url(line):
    """Return whether a line contains an http(s) URL and is therefore exempt.

    Args:
        line: A single commit-message line.

    Returns:
        bool: True when the line contains a URL.
    """
    return bool(_URL_IN_LINE_RE.search(line))


def _is_indented_line(line):
    """Return whether a non-blank line begins with whitespace.

    Args:
        line: A single commit-message line.

    Returns:
        bool: True when the line has leading whitespace.
    """
    return bool(line) and line[0].isspace()


def _is_list_item_line(line):
    """Return whether a line looks like a markdown list item.

    Args:
        line: A single commit-message line.

    Returns:
        bool: True when the stripped line starts with a list marker.
    """
    return bool(_LIST_ITEM_RE.match(line.lstrip()))


def _match_code_fence(line):
    """Return fence metadata when a line is a fence marker.

    Args:
        line: A single commit-message line.

    Returns:
        tuple[int, str, str] | None: ``(tick_count, info, fence_char)`` for a
        fence line with at most three leading spaces, otherwise ``None``.
        ``fence_char`` is a backtick or tilde.
    """
    match = _CODE_FENCE_RE.match(line)
    if not match:
        return None
    fence = match.group(2)
    return len(fence), match.group(3), fence[0]


def _is_valid_fence_opener(tick_count, info, fence_char):
    """Return whether fence metadata is a valid CommonMark-ish opener.

    Backtick fence info may not contain backticks; tilde fence info may not
    contain tildes. That keeps inline samples like `` ```example``` `` from
    opening a fence region and trapping later wrap-eligible prose.

    Args:
        tick_count: Marker count from the matched fence line.
        info: Raw info string after the fence markers.
        fence_char: Backtick or tilde from the matched fence line.

    Returns:
        bool: True when the match may open a fenced region.
    """
    if tick_count < 3 or fence_char not in ("`", "~"):
        return False
    if fence_char in info:
        return False
    return True


def _is_code_fence_line(
    line, in_code_fence=False, open_fence_ticks=0, open_fence_char=""
):
    """Return whether a line opens or closes a fenced code block.

    Opening fences may carry a language/info string, but backtick openers
    reject info containing backticks and tilde openers reject info containing
    tildes. Closing fences must use the same fence character as the opener,
    have an empty info string (optional trailing whitespace), and be at least
    as long as the opening fence. Lines indented with 4+ spaces are not
    treated as fences, so indented code samples cannot flip fence state.

    Args:
        line: A single commit-message line.
        in_code_fence: Whether the formatter is currently inside a fence region.
        open_fence_ticks: Marker count from the opening fence when inside a
            fence region; closing fences must have at least this many markers.
        open_fence_char: Backtick or tilde from the opening fence when inside a
            fence region; closing fences must use the same character.

    Returns:
        bool: True when the line should toggle fence state.
    """
    matched = _match_code_fence(line)
    if not matched:
        return False
    tick_count, info, fence_char = matched
    if in_code_fence:
        return (
            fence_char == open_fence_char
            and info.strip() == ""
            and tick_count >= open_fence_ticks
        )
    return _is_valid_fence_opener(tick_count, info, fence_char)


def _is_non_reflow_line(line, in_code_fence):
    """Return whether a line must be left unchanged by paragraph reflow.

    Structural lines (URLs, indentation, list markers, and fenced code regions)
    are exempt so wrapping does not damage paragraph structure. Fence-shaped
    lines stay exempt even when they are not valid openers, so inline samples
    are not merged into surrounding prose.

    Args:
        line: A single commit-message line.
        in_code_fence: Whether the formatter is currently inside a fence region.

    Returns:
        bool: True when the line should be appended unchanged after a flush.
    """
    if _line_contains_url(line):
        return True
    if in_code_fence or _match_code_fence(line) is not None:
        return True
    if _is_indented_line(line):
        return True
    if _is_list_item_line(line):
        return True
    return False


def format_commit_body(body, max_length=COMMIT_BODY_MAX_LINE_LENGTH):
    """Wrap wrap-eligible commit body lines to a maximum length.

    Blank lines, URL-bearing lines, indented lines, list items, and fenced
    code regions are preserved unchanged. Ordinary prose is reflowed and
    wrapped; overlong non-URL tokens inside that prose may be hard-split.

    Args:
        body: Commit body text to format.
        max_length: Maximum width for wrapped lines.

    Returns:
        str: The formatted body with blank lines and structure preserved.
    """
    if not isinstance(body, str) or not body:
        return body

    wrapper = TextWrapper(
        width=max_length,
        break_long_words=True,
        break_on_hyphens=False,
    )
    formatted_lines = []
    paragraph_lines = []
    in_code_fence = False
    open_fence_ticks = 0
    open_fence_char = ""

    def flush_paragraph():
        """Wrap the accumulated paragraph as a single prose block."""
        if paragraph_lines:
            paragraph = " ".join(line.strip() for line in paragraph_lines)
            formatted_lines.extend(wrapper.wrap(paragraph))
            paragraph_lines.clear()

    for line in body.splitlines():
        if not line.strip():
            flush_paragraph()
            formatted_lines.append(line)
            continue
        if _is_non_reflow_line(line, in_code_fence):
            flush_paragraph()
            formatted_lines.append(line)
            if _is_code_fence_line(
                line, in_code_fence, open_fence_ticks, open_fence_char
            ):
                if in_code_fence:
                    in_code_fence = False
                    open_fence_ticks = 0
                    open_fence_char = ""
                else:
                    matched = _match_code_fence(line)
                    in_code_fence = True
                    if matched:
                        open_fence_ticks = matched[0]
                        open_fence_char = matched[2]
                    else:
                        open_fence_ticks = 0
                        open_fence_char = ""
            continue
        paragraph_lines.append(line)

    flush_paragraph()
    return "\n".join(formatted_lines)


def format_commit_message(message, max_length=COMMIT_BODY_MAX_LINE_LENGTH):
    """Format a commit message while preserving its subject and body structure.

    Args:
        message: Full commit message text to format.
        max_length: Maximum width for wrapped body lines.

    Returns:
        str: The stripped message with its body formatted, or the stripped
            original message when no body exists.
    """
    if not isinstance(message, str) or not message.strip():
        return message.strip() if isinstance(message, str) else message

    stripped_message = message.strip()
    body = _extract_commit_body(stripped_message)
    if not body:
        return stripped_message

    subject = stripped_message.splitlines()[0]
    formatted_body = format_commit_body(body, max_length=max_length)
    return f"{subject}\n\n{formatted_body}"


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

        generation_config = _get_commit_generation_config()
        commit_model = generation_config["model"]
        logger.info(
            "Requesting suggested commit message for staged changes using model=%r.",
            commit_model,
        )
        try:
            commit_message = get_suggested_commit_message(
                diff_output, model=commit_model
            )
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
            f"\n\n\nSuggested commit message (model: {commit_model}):\n\n"
            f"{yellow}{commit_message}{reset}\n\n"
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


def _generate_commit_message_once(diff_output, model=None):
    """Generate one commit-message candidate from a staged diff.

    Args:
        diff_output: The staged git diff to summarize.
        model: Optional resolved model name. When omitted, the commit-specific
            model configuration is resolved by this function.

    Returns:
        str: A generated commit message (possibly empty).

    Uses a stateless ``litellm.completion`` call rather than ``query()`` so the
    diff and the generated message are NOT appended to the live conversation
    history — generating a commit message shouldn't pollute the model's context
    or token/cost accounting for subsequent turns.
    """
    query_input = build_commit_message_query_input(
        diff=diff_output,
        macro_values=MACRO_VALUES,
        macro_delim_open=config.MACRO_DELIMITER_OPEN,
        macro_delim_close=config.MACRO_DELIMITER_CLOSE,
        macro_delim_escape=config.MACRO_DELIMITER_ESCAPE,
    )
    logger.debug("Built commit message query input for staged changes.")
    generation_config = _get_commit_generation_config()
    resolved_model = model or generation_config["model"]
    kwargs = _build_commit_completion_kwargs(
        resolved_model,
        generation_config["reasoning_effort"],
        generation_config["reasoning_max_completion_tokens"],
    )
    kwargs["messages"] = [
        {
            "role": "system",
            "content": dedent(
                """
                You write clear git commit messages.
                """
            ).strip(),
        },
        {"role": "user", "content": query_input},
    ]
    with progress_dots("Generating commit message"):
        log_helper_model_usage("commit_message", kwargs["model"])
        response = call_litellm_completion(
            kwargs["model"],
            kwargs["messages"],
            tool_descriptions=[],
            gemini_tool_descriptions=[],
            reasoning_effort=kwargs.get("reasoning_effort"),
            max_completion_tokens=kwargs.get("max_completion_tokens"),
        )
    return response.choices[0].message.content or ""


def get_suggested_commit_message(diff_output, model=None):
    """
    Return a formatted suggested commit message based on staged git changes.

    Args:
        diff_output: The staged git diff to summarize.
        model: Optional resolved model name. When omitted, the commit-specific
            model configuration is resolved by this function.

    Returns:
        str: A generated commit message with non-URL body lines formatted to the
            configured maximum line length.
    """
    logger.debug(
        "Entering get_suggested_commit_message to generate message from staged changes."
    )
    try:
        commit_message = _generate_commit_message_once(diff_output, model=model)
        formatted_message = format_commit_message(commit_message)
        logger.debug("Generated and formatted suggested commit message.")
        return formatted_message
    except Exception as e:
        logger.error(f"Error generating suggested commit message: {e}", exc_info=True)
        raise
