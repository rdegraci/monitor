"""Assistant-response helper commands for built-in command dispatch."""

import logging
import os
import sys
import time

from monitor import config
from monitor.lib.display_output import print_colored_error

logger = logging.getLogger(__name__)


def _last_assistant_response() -> str | None:
    """Return the latest non-empty assistant message content.

    Returns:
        The most recent non-empty assistant message content, or ``None`` when
        there is no such message.
    """
    history = getattr(config, "CONVERSATION_HISTORY", None) or []
    for message in reversed(history):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
    return None


def _extract_fenced_code_blocks(text: str) -> list[tuple[str, str]]:
    """Extract triple-backtick fenced code blocks from text.

    Args:
        text: Source markdown text.

    Returns:
        A list of ``(language, code)`` tuples.
    """
    import re

    pattern = re.compile(r"```([A-Za-z0-9_+\-.]*)\n(.*?)\n?```", re.DOTALL)
    return [(match.group(1), match.group(2)) for match in pattern.finditer(text)]


def less_command(arg: str = None) -> None:
    """Re-display the most recent assistant response through a pager.

    Args:
        arg: Ignored dispatcher argument.

    Returns:
        None.
    """
    del arg
    text = _last_assistant_response()
    if text is None:
        print("No assistant response to page yet.")
        return

    if not sys.stdout.isatty():
        print(text)
        return

    try:
        from rich.console import Console
        from rich.markdown import Markdown
    except ImportError:
        logger.warning("rich not available; printing response inline.")
        print(text)
        return

    unset = object()
    prev_less = os.environ.get("LESS", unset)
    os.environ["LESS"] = "-R"
    try:
        console = Console()
        with console.pager(styles=True):
            console.print(Markdown(text))
    except BrokenPipeError:
        pass
    except Exception as exc:
        logger.warning("Pager render failed (%s); printing response inline.", exc)
        print(text)
    finally:
        if prev_less is unset:
            os.environ.pop("LESS", None)
        else:
            os.environ["LESS"] = prev_less


def copy_code_command(arg: str = None) -> None:
    """Copy fenced code blocks from the latest assistant response.

    Args:
        arg: Optional selector: empty for the first block, ``all``, or a
            1-indexed block number.

    Returns:
        None.
    """
    text = _last_assistant_response()
    if text is None:
        print_colored_error("No assistant response to copy from yet.")
        return

    blocks = _extract_fenced_code_blocks(text)
    if not blocks:
        print_colored_error(
            "No code block found in the last response. Only ``` fenced blocks "
            "are recognized; inline `code` is ignored."
        )
        return

    raw = (arg or "").strip()
    if not raw:
        selected = [blocks[0][1]]
        label = f"first of {len(blocks)} block{'s' if len(blocks) != 1 else ''}"
    elif raw.lower() == "all":
        selected = [code for _lang, code in blocks]
        label = f"all {len(blocks)} block{'s' if len(blocks) != 1 else ''}"
    else:
        try:
            index = int(raw)
        except ValueError:
            print_colored_error(
                f"Invalid argument: {raw!r}. Usage: : (or /) copy_code [N | all]. "
                f"The last response has {len(blocks)} block{'s' if len(blocks) != 1 else ''}."
            )
            return
        if index < 1 or index > len(blocks):
            print_colored_error(
                f"Block index {index} out of range — last response has "
                f"{len(blocks)} block{'s' if len(blocks) != 1 else ''} (1-indexed)."
            )
            return
        selected = [blocks[index - 1][1]]
        label = f"block {index} of {len(blocks)}"

    payload = "\n\n".join(selected)

    try:
        import pyperclip

        pyperclip.copy(payload)
    except ImportError:
        logger.warning("pyperclip not installed; printing code inline.")
        print(payload)
        print("[clipboard unavailable: pyperclip not installed — copied above as plain text]")
        return
    except Exception as exc:
        logger.warning("Clipboard copy failed (%s); printing code inline.", exc)
        print(payload)
        print(f"[clipboard unavailable: {exc} — copied above as plain text]")
        return

    print(f"Copied {label} to clipboard ({len(payload)} chars).")


def save_response_command(arg: str = None) -> None:
    """Write the most recent assistant response to a file.

    Args:
        arg: Optional output directory or file path.

    Returns:
        None.
    """
    text = _last_assistant_response()
    if text is None:
        print_colored_error("No assistant response to save yet.")
        return

    raw = (arg or "").strip()
    default_filename = f"response-{int(time.time())}.md"

    if not raw:
        target = os.path.join(os.getcwd(), default_filename)
    else:
        expanded = os.path.abspath(os.path.expanduser(raw))
        if os.path.isdir(expanded):
            target = os.path.join(expanded, default_filename)
        else:
            target = expanded

    parent = os.path.dirname(target) or "."
    if not os.path.isdir(parent):
        print_colored_error(f"Parent directory does not exist: {parent}. Create it first.")
        return

    try:
        with open(target, "w", encoding="utf-8") as file_handle:
            file_handle.write(text)
            if not text.endswith("\n"):
                file_handle.write("\n")
    except OSError as exc:
        print_colored_error(f"Failed to write response to {target}: {exc}")
        return

    print(f"Wrote assistant response ({len(text)} chars) to {target}")
