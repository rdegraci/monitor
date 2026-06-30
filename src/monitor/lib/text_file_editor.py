"""
Text file editor utilities with line numbers and syntax highlighting.

This module provides functions for viewing, creating, and editing text files
with enhanced terminal output including line numbers and syntax highlighting.
"""

import difflib
import logging
import os
from typing import Any, Dict, List, Optional
from monitor.lib.pygments_stubs import DiffLexer, TerminalFormatter, highlight
from monitor.lib.pygments_stubs import DiffLexer, TerminalFormatter, highlight
from monitor.lib.third_party_shims import ClassNotFound, get_lexer_for_filename, TextLexer

from monitor.lib.colors import blue, red, yellow, green, reset, print_colored, print_blue, print_red, print_yellow, print_green
from monitor.lib.file_io import (
    read_file,
    write_file,
    create_file,
    list_directory,
    is_file,
    is_directory,
    make_dirs,
)

logger = logging.getLogger(__name__)

# Cap on the diff returned in the tool result so a large change doesn't
# bloat the model's context (the full diff is still printed to the terminal).
MAX_DIFF_RESULT_CHARS = 8000


def _compute_and_print_diff(original: str, updated: str, path: str) -> str:
    """Return a unified-diff string for the change and print it to the terminal
    with diff syntax highlighting. No tmp file required.
    """
    diff_text = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    if diff_text:
        try:
            print(highlight(diff_text, DiffLexer(), TerminalFormatter(reset=True)))
        except Exception:
            print(diff_text)
    return diff_text


def _truncate_diff(diff_text: str) -> str:
    if len(diff_text) <= MAX_DIFF_RESULT_CHARS:
        return diff_text
    return diff_text[:MAX_DIFF_RESULT_CHARS] + "\n... [diff truncated] ..."


def print_with_insert_lines(content: str, start_line: int = 1, path: Optional[str] = None):
    """Print content with line numbers and optional syntax highlighting."""
    lines = content.splitlines()
    
    # Try to get syntax highlighting based on file extension
    lexer = TextLexer()
    if path:
        try:
            lexer = get_lexer_for_filename(path)
        except ClassNotFound:
            lexer = TextLexer()
    
    # Apply syntax highlighting
    try:
        highlighted_content = highlight(content, lexer, TerminalFormatter(reset=True))
        highlighted_lines = highlighted_content.splitlines()
    except:
        # Fallback to plain text if highlighting fails
        highlighted_lines = lines
    
    # Ensure we have the same number of lines
    if len(highlighted_lines) != len(lines):
        highlighted_lines = lines
    
    # Calculate the width needed for line numbers
    total_lines = len(lines)
    line_num_width = len(str(start_line + total_lines - 1))
    
    print_colored(f"File: {path or 'content'}", blue)
    print_colored("─" * 50, blue)
    
    for i, line in enumerate(highlighted_lines):
        line_num = start_line + i
        line_num_str = str(line_num).rjust(line_num_width)
        print(f"{blue}{line_num_str}{reset} │ {line}")
    
    print_colored("─" * 50, blue)


def text_file_or_directory_view(command: str, path: Optional[str], view_range: Optional[List[int]] = None) -> str:
    """
    View the contents of a file with optional line range or list the contents of a directory. 
    When viewing files, supports syntax highlighting and line numbers. When viewing directories, 
    lists all contained files and subdirectories.
    
    Args:
        command: The command type - must be 'view'
        path: The path to the file or directory to view
        view_range: Optional array of two integers [start_line, end_line] specifying the line range 
                   to view. Line numbers are 1-indexed. Use -1 for end_line to read to the end of 
                   the file. Only applies when viewing files, not directories.
    
    Returns:
        The file contents as a string (for files), the directory listing as a formatted string (for directories),
        or an error description.
    """
    logger.debug("Command: %s, Path: %s, view_range: %s", command, path, view_range)
    
    # Validate command parameter
    if command != "view":
        print_red(f"Invalid command '{command}'. Must be 'view'")
        return f"Invalid command '{command}'. Must be 'view'"
    
    if path is None:
        print_red("Path must be provided")
        return "Path must be provided"
    path_str = path

    isf = is_file(path_str)
    isd = is_directory(path_str)
    if not (isf or isd):
        print_red(f"Path not found: {path}")
        return f"Path not found: {path}"

    if view_range is not None:
        if not isf:
            print_red(f"view_range parameter only applies to files, but '{path}' is not a file")
            return f"view_range parameter only applies to files, but '{path}' is not a file"
        
        if not isinstance(view_range, list) or len(view_range) != 2:
            print_red("view_range must be an array of exactly 2 integers [start_line, end_line]")
            return "view_range must be an array of exactly 2 integers [start_line, end_line]"
        
        start_line, end_line = view_range

        if not isinstance(start_line, int) or not isinstance(end_line, int):
            print_red("view_range elements must be integers")
            return "view_range elements must be integers"

        file_content = read_file(path_str)
        if file_content is None:
            print_red("Error reading file or file does not exist.")
            return "Error reading file or file does not exist."
        
        lines = file_content.splitlines(keepends=True)
        total_lines = len(lines)

        if end_line == -1:
            end_line = total_lines
        
        if start_line < 1:
            print_red("start_line must be >= 1")
            return "start_line must be >= 1"
        if start_line > total_lines:
            print_red(f"start_line {start_line} exceeds file length ({total_lines} lines)")
            return f"start_line {start_line} exceeds file length ({total_lines} lines)"
        
        if end_line < 1:
            print_red("end_line must be >= 1 (or -1 for end of file)")
            return "end_line must be >= 1 (or -1 for end of file)"
        if end_line > total_lines:
            print_red(f"end_line {end_line} exceeds file length ({total_lines} lines)")
            return f"end_line {end_line} exceeds file length ({total_lines} lines)"
        
        if start_line > end_line:
            print_red(f"start_line ({start_line}) cannot be greater than end_line ({end_line})")
            return f"start_line ({start_line}) cannot be greater than end_line ({end_line})"
        
        actual_start = start_line - 1
        actual_end = end_line

        selected_lines = lines[actual_start:actual_end]
        content_to_display = ''.join(selected_lines)
        
        print_with_insert_lines(content_to_display.rstrip('\n'), actual_start + 1, path_str)
        
        logger.info(f"Displayed lines {start_line}-{end_line} of {path} (total: {total_lines} lines)")
        return content_to_display

    if isd:
        entries = list_directory(path_str)
        if entries is None:
            print_red("Error reading directory or directory does not exist.")
            return "Error reading directory or directory does not exist."
        entries.sort()
        
        print_blue(f"Directory: {path_str}")
        print_blue("─" * 50)
        
        directory_listing_lines = []
        if not entries:
            print_yellow("(empty directory)")
            directory_listing_lines.append("(empty directory)")
        else:
            for entry in entries:
                entry_path = f"{path_str}/{entry}"
                if is_directory(entry_path):
                    text = f"📁 {entry}/"
                    print_blue(text)
                    directory_listing_lines.append(text)
                else:
                    text = f"📄 {entry}"
                    print(text)
                    directory_listing_lines.append(text)
        
        print_blue("─" * 50)
        
        logger.info(f"Listed directory {path} ({len(entries)} entries)")
        return "\n".join(directory_listing_lines)
    elif isf:
        content = read_file(path)
        if content is None:
            print_red("Error reading file or file does not exist.")
            return "Error reading file or file does not exist."
        print_with_insert_lines(content, 1, path_str)
        logger.info(f"Displayed entire file {path} ({content.count(chr(10)) + (1 if content and not content.endswith(chr(10)) else 0)} lines)")
        return content
    else:
        print_red(f"Path '{path}' is neither a file nor a directory")
        return f"Path '{path}' is neither a file nor a directory"


def text_file_create(command: str, path: str, content: str) -> Dict[str, Any]:
    """
    Create a new file with the specified content. Will fail if the file already exists.
    Parent directories are created automatically if missing.

    Returns:
        Dict {"ok": True, "path", "lines_created", "message"} on success, or
        {"ok": False, "path", "error"} on failure.
    """
    logger.debug("Creating file: %s", path)

    # Blast-radius cap: reject oversized writes before any disk work.
    from monitor.lib.safety import check_write_size
    ok, err = check_write_size(content, "text_file_create")
    if not ok:
        logger.warning("text_file_create: %s", err)
        return {"ok": False, "path": path, "error": err}

    if is_file(path):
        msg = f"File already exists: {path}"
        print_red(msg)
        return {"ok": False, "path": path, "error": msg}

    directory = os.path.dirname(path)
    if directory and not is_directory(directory):
        make_dirs(directory)
        logger.debug("Created directory: %s", directory)

    create_success = create_file(path, content)
    if not create_success:
        msg = f"Error creating file: {path}"
        print_red(msg)
        return {"ok": False, "path": path, "error": msg}

    lines_created = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
    success_msg = f"Created new file: {path} ({lines_created} lines)"
    print_green(success_msg)
    logger.info(success_msg)
    return {
        "ok": True,
        "path": path,
        "lines_created": lines_created,
        "message": success_msg,
    }


def text_file_str_replace_in_file(command: str, path: str, old_str: str, new_str: str) -> Dict[str, Any]:
    """
    Replace an exact string in a file. The old_str must match exactly once.

    Returns:
        Dict {"ok": True, "path", "lines_changed", "diff", "message"} on success,
        or {"ok": False, "path", "error"} on any failure including
        zero-match or multi-match.
    """
    logger.debug("String replace in file: %s", path)

    # Blast-radius cap on new_str (the payload that gets written). old_str
    # is just a search needle; it doesn't grow the file.
    from monitor.lib.safety import check_write_size
    ok, err = check_write_size(new_str, "text_file_str_replace_in_file")
    if not ok:
        logger.warning("text_file_str_replace_in_file: %s", err)
        return {"ok": False, "path": path, "error": err}

    if not is_file(path):
        msg = f"File not found or not a file: {path}"
        print_red(msg)
        return {"ok": False, "path": path, "error": msg}

    original = read_file(path)
    if original is None:
        msg = f"Error reading file: {path}"
        print_red(msg)
        return {"ok": False, "path": path, "error": msg}

    occurrence_count = original.count(old_str)
    if occurrence_count == 0:
        snippet = old_str[:50] + ("..." if len(old_str) > 50 else "")
        msg = f"String not found in {path}: '{snippet}'"
        print_red(msg)
        return {"ok": False, "path": path, "error": msg}
    if occurrence_count > 1:
        snippet = old_str[:50] + ("..." if len(old_str) > 50 else "")
        msg = (
            f"old_str matches {occurrence_count} times in {path}; surgical replace "
            f"requires exactly one match. Include more surrounding context in "
            f"old_str to make it unique. Pattern: '{snippet}'"
        )
        print_red(msg)
        return {"ok": False, "path": path, "error": msg}

    new_content = original.replace(old_str, new_str)
    diff_text = _compute_and_print_diff(original, new_content, path)

    if not write_file(path, new_content):
        msg = f"Error writing updated file: {path}"
        print_red(msg)
        return {"ok": False, "path": path, "error": msg}

    lines_changed = len(new_content.splitlines()) - len(original.splitlines())
    success_msg = f"Replaced 1 occurrence in {path}"
    print_yellow(success_msg)
    logger.info(success_msg)
    return {
        "ok": True,
        "path": path,
        "lines_changed": lines_changed,
        "diff": _truncate_diff(diff_text),
        "message": success_msg,
    }


def text_file_insert_text_at_line(command: str, path: str, insert_line: int, new_str: str) -> Dict[str, Any]:
    """
    Insert new_str BEFORE the 1-based ``insert_line`` in a file.
    ``insert_line=1`` inserts at the top of the file;
    ``insert_line=total_lines + 1`` appends to the end.

    Returns:
        Dict {"ok": True, "path", "inserted_at_line", "lines_changed",
              "diff", "message"} on success, or
        {"ok": False, "path", "error"} on failure.
    """
    logger.debug("Inserting new_str at line %d in file: %s", insert_line, path)

    # Blast-radius cap on the inserted payload. Even insert-at-line could
    # accept a hallucinated multi-MB string; check before disk work.
    from monitor.lib.safety import check_write_size
    ok, err = check_write_size(new_str, "text_file_insert_text_at_line")
    if not ok:
        logger.warning("text_file_insert_text_at_line: %s", err)
        return {"ok": False, "path": path, "error": err}

    if not is_file(path):
        msg = f"File not found or not a file: {path}"
        print_red(msg)
        return {"ok": False, "path": path, "error": msg}

    if insert_line < 1:
        msg = f"insert_line must be >= 1 (got {insert_line})"
        print_red(msg)
        return {"ok": False, "path": path, "error": msg}

    original = read_file(path)
    if original is None:
        msg = f"Error reading file: {path}"
        print_red(msg)
        return {"ok": False, "path": path, "error": msg}

    lines = original.splitlines(keepends=True)
    total_lines = len(lines)
    if insert_line > total_lines + 1:
        msg = (
            f"insert_line {insert_line} exceeds file length ({total_lines} lines); "
            f"maximum allowed is {total_lines + 1} (which appends to the end)."
        )
        print_red(msg)
        return {"ok": False, "path": path, "error": msg}

    if new_str and not new_str.endswith('\n'):
        new_str += '\n'
    lines.insert(insert_line - 1, new_str)
    new_content = ''.join(lines)

    diff_text = _compute_and_print_diff(original, new_content, path)

    if not write_file(path, new_content):
        msg = f"Error writing updated file: {path}"
        print_red(msg)
        return {"ok": False, "path": path, "error": msg}

    lines_changed = len(new_content.splitlines()) - len(original.splitlines())
    success_msg = f"Inserted at line {insert_line} in {path}"
    print_yellow(success_msg)
    logger.info(success_msg)
    return {
        "ok": True,
        "path": path,
        "inserted_at_line": insert_line,
        "lines_changed": lines_changed,
        "diff": _truncate_diff(diff_text),
        "message": success_msg,
    }


def _normalize_text_file_result(result: Any) -> Dict[str, Any]:
    """Adapt an underlying text_file_* tool result to Anthropic's editor-tool
    success/error envelope.

    The four surgical tools have heterogeneous return shapes:
      - text_file_or_directory_view returns a *string* (the content/listing,
        or a leading error phrase like "Path not found: ...").
      - text_file_create / text_file_str_replace_in_file /
        text_file_insert_text_at_line return *dicts* of the form
        ``{"ok": bool, ..., "message"|"error": str}``.

    This helper papers over both so the dispatcher can hand back a uniform
    ``{success, message}`` / ``{success, error}`` envelope without each branch
    duplicating the shape detection.
    """
    if isinstance(result, dict):
        if result.get("ok"):
            return {"success": True, "message": result.get("message") or result.get("diff") or ""}
        return {"success": False, "error": result.get("error") or "unknown error"}

    if isinstance(result, str):
        # Heuristic for the string-returning view tool: leading error-phrase
        # prefixes mark failures; everything else is real content.
        error_prefixes = (
            "Path not found", "Invalid command", "view_range", "start_line",
            "end_line", "Permission denied", "Unable to decode", "Error",
            "Path '",
        )
        if any(result.startswith(p) for p in error_prefixes):
            return {"success": False, "error": result}
        return {"success": True, "message": result}

    return {"success": True, "message": str(result)}


def str_replace_based_edit_tool(command: str, path: str, **kwargs) -> Dict[str, Any]:
    """Dispatcher for Anthropic-native editor tools.

    Routes the model's ``command`` (view / create / str_replace / insert) to the
    corresponding surgical text_file_* implementation and adapts each result to
    a uniform ``{success, message|error}`` envelope. Registered in
    AVAILABLE_TOOLS under both ``str_replace_based_edit_tool`` and
    ``str_replace_editor`` (the older Anthropic name).
    """
    logger.debug("str_replace_based_edit_tool: command=%s, path=%s, kwargs=%s", command, path, kwargs)

    try:
        if command == "view":
            view_range = kwargs.get("view_range")
            if view_range and not (isinstance(view_range, list) and len(view_range) == 2):
                return {"success": False, "error": "view_range must be a list of two integers [start_line, end_line]"}
            return _normalize_text_file_result(
                text_file_or_directory_view(command, path, view_range if view_range else None)
            )

        elif command == "create":
            file_text = kwargs.get("file_text", "")
            return _normalize_text_file_result(text_file_create(command, path, file_text))

        elif command == "str_replace":
            old_str = kwargs.get("old_str")
            new_str = kwargs.get("new_str")
            if old_str is None:
                return {"success": False, "error": "old_str parameter is required for str_replace command"}
            if new_str is None:
                return {"success": False, "error": "new_str parameter is required for str_replace command"}
            return _normalize_text_file_result(
                text_file_str_replace_in_file(command, path, old_str, new_str)
            )

        elif command == "insert":
            insert_line = kwargs.get("insert_line")
            new_str = kwargs.get("new_str")
            if insert_line is None:
                return {"success": False, "error": "insert_line parameter is required for insert command"}
            if new_str is None:
                return {"success": False, "error": "new_str parameter is required for insert command"}
            return _normalize_text_file_result(
                text_file_insert_text_at_line(command, path, insert_line, new_str)
            )

        else:
            return {"success": False, "error": f"Unknown command: {command}"}

    except Exception as e:
        error_msg = f"Error executing command '{command}': {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"success": False, "error": error_msg}
