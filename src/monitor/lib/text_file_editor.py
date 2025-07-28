"""
Text file editor utilities with line numbers and syntax highlighting.

This module provides functions for viewing, creating, and editing text files
with enhanced terminal output including line numbers and syntax highlighting.
"""

import logging
import json
from typing import Optional, Dict, Any, Union, List
from pygments import highlight
from pygments.lexers import get_lexer_for_filename, TextLexer, DiffLexer
from pygments.formatters import TerminalFormatter
from pygments.util import ClassNotFound

from monitor.lib.os import run_diff, print_diff
from monitor.lib.colors import blue, red, yellow, green, reset, print_colored, print_blue, print_red, print_yellow, print_green
from monitor.lib.file_io import (
    read_file,
    write_file,
    create_file,
    file_exists,
    delete_file,
    list_directory,
    is_file,
    is_directory,
    make_dirs,
)

logger = logging.getLogger(__name__)


def print_with_insert_lines(content: str, start_line: int = 1, path: str = None):
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


def text_file_or_directory_view(command: str, path: str, view_range: Optional[List[int]] = None) -> str:
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
    
    if not file_exists(path):
        print_red(f"Path not found: {path}")
        return f"Path not found: {path}"

    isf = is_file(path)
    isd = is_directory(path)

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

        file_content = read_file(path)
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
        
        print_with_insert_lines(content_to_display.rstrip('\n'), actual_start + 1, path)
        
        logger.info(f"Displayed lines {start_line}-{end_line} of {path} (total: {total_lines} lines)")
        return content_to_display

    if isd:
        entries = list_directory(path)
        if entries is None:
            print_red("Error reading directory or directory does not exist.")
            return "Error reading directory or directory does not exist."
        entries.sort()
        
        print_blue(f"Directory: {path}")
        print_blue("─" * 50)
        
        directory_listing_lines = []
        if not entries:
            print_yellow("(empty directory)")
            directory_listing_lines.append("(empty directory)")
        else:
            for entry in entries:
                entry_path = f"{path}/{entry}"
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
        print_with_insert_lines(content, 1, path)
        logger.info(f"Displayed entire file {path} ({content.count(chr(10)) + (1 if content and not content.endswith(chr(10)) else 0)} lines)")
        return content
    else:
        print_red(f"Path '{path}' is neither a file nor a directory")
        return f"Path '{path}' is neither a file nor a directory"


def text_file_create(command: str, path: str, content: str) -> str:
    """
    Create a new file with the specified content. Will fail if the file already exists.
    
    Args:
        path: The path where the new file should be created
        content: The content to write to the new file
    
    Returns:
        The written file contents as a string, or error description
    """
    logger.debug("Creating file: %s", path)

    if file_exists(path):
        print_red(f"File already exists: {path}")
        return f"File already exists: {path}"

    directory = path.rpartition('/')[0]
    if directory and not file_exists(directory):
        make_dirs(directory)
        logger.debug("Created directory: %s", directory)

    create_success = create_file(path, content)
    if not create_success:
        print_red("Error creating file.")
        return "Error creating file."

    line_count = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
    success_msg = f"Created new file: {path} ({line_count} lines)"
    print_green(success_msg)
    logger.info(success_msg)
    return content


def text_file_str_replace_in_file(command: str, path: str, old_str: str, new_str: str) -> str:
    """
    Replace a specific string in a file with new content. The old string must match exactly.
    
    Args:
        path: The path to the file to edit
        old_str: The exact string to find and replace
        new_str: The string to replace the old string with
    
    Returns:
        Full updated file contents as a string, or error description
    """
    logger.debug("String replace in file: %s", path)

    if not file_exists(path):
        print_red(f"File not found: {path}")
        return f"File not found: {path}"

    if not is_file(path):
        print_red(f"Path is not a file: {path}")
        return f"Path is not a file: {path}"

    original_content = read_file(path)
    if original_content is None:
        print_red("Error reading file or file does not exist.")
        return "Error reading file or file does not exist."

    if old_str not in original_content:
        print_red(f"String not found in file: '{old_str[:50]}{'...' if len(old_str) > 50 else ''}'")
        return f"String not found in file: '{old_str[:50]}{'...' if len(old_str) > 50 else ''}'"

    occurrence_count = original_content.count(old_str)
    if occurrence_count > 1:
        print_yellow(f"Warning: Found {occurrence_count} occurrences of the target string. All will be replaced.")

    new_content = original_content.replace(old_str, new_str)

    tmp_path = f"{path}.tmp"
    write_tmp_success = write_file(tmp_path, new_content)
    if not write_tmp_success:
        print_red("Error writing temporary file.")
        return "Error writing temporary file."

    diff_json = run_diff(path, tmp_path)
    try:
        diff_result = json.loads(diff_json)
    except Exception as e:
        print_red(f"Error parsing diff result: {str(e)}")
        return f"Error parsing diff result: {str(e)}"
    if diff_result.get("success"):
        print_diff(diff_result.get("stdout"))

    # replace original with new
    os_result = write_file(path, new_content)
    if not os_result:
        print_red("Error writing updated file.")
        return "Error writing updated file."
    delete_file(tmp_path)

    success_msg = f"Successfully replaced {occurrence_count} occurrence(s) in {path}"
    print_green(success_msg)
    logger.info(success_msg)

    return new_content


def text_file_insert_text_at_line(command: str, path: str, insert_line: int, new_str: str) -> str:
    """
    Insert new_str at a specific line number in a file. The new_str will be inserted before the specified line.
    
    Args:
        path: The path to the file to edit
        insert_line: The line number where new_str should be inserted (1-indexed)
        new_str: The new_str to insert at the specified line
    
    Returns:
        Full updated file contents as a string, or error description
    """
    logger.debug("Inserting new_str at line %d in file: %s", insert_line, path)

    if not file_exists(path):
        print_red(f"File not found: {path}")
        return f"File not found: {path}"

    if not is_file(path):
        print_red(f"Path is not a file: {path}")
        return f"Path is not a file: {path}"

    if insert_line < 1:
        print_red("Line number must be >= 1")
        return "Line number must be >= 1"

    content = read_file(path)
    if content is None:
        print_red("Error reading file or file does not exist.")
        return "Error reading file or file does not exist."

    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    if insert_line > total_lines + 1:
        print_red(f"Line number {insert_line} exceeds file length ({total_lines} lines). Maximum allowed: {total_lines + 1}")
        return f"Line number {insert_line} exceeds file length ({total_lines} lines). Maximum allowed: {total_lines + 1}"

    if new_str and not new_str.endswith('\n'):
        new_str += '\n'
    insert_index = insert_line - 1
    lines.insert(insert_index, new_str)

    tmp_path = f"{path}.tmp"
    tmp_content = ''.join(lines)
    write_tmp_success = write_file(tmp_path, tmp_content)
    if not write_tmp_success:
        print_red("Error writing temporary file.")
        return "Error writing temporary file."

    diff_json = run_diff(path, tmp_path)
    try:
        diff_result = json.loads(diff_json)
    except Exception as e:
        print_red(f"Error parsing diff result: {str(e)}")
        return f"Error parsing diff result: {str(e)}"
    if diff_result.get("success"):
        print_diff(diff_result.get("stdout"))
    # Replace original
    final_write_result = write_file(path, tmp_content)
    if not final_write_result:
        print_red("Error writing updated file.")
        return "Error writing updated file."
    delete_file(tmp_path)

    success_msg = f"Successfully inserted new_str at line {insert_line} in {path}"
    print_green(success_msg)
    logger.info(success_msg)

    return tmp_content


def str_replace_based_edit_tool(command: str, path: str, **kwargs) -> Dict[str, Any]:
    """
    Handle the Anthropic text editor tool commands.
    
    Args:
        command: The command to execute ('view', 'create', 'str_replace', 'insert')
        path: The file path to operate on
        **kwargs: Additional command-specific arguments
    
    Returns:
        Dictionary with success status and message
    """
    logger.debug("str_replace_based_edit_tool: command=%s, path=%s, kwargs=%s", command, path, kwargs)
    
    try:
        if command == "view":
            view_range = kwargs.get("view_range")
            start_line = None
            end_line = None
            if view_range:
                if isinstance(view_range, list) and len(view_range) == 2:
                    start_line, end_line = view_range
                else:
                    return {
                        "success": False,
                        "error": "view_range must be a list of two integers [start_line, end_line]"
                    }
            
            result = text_file_or_directory_view(command, path, view_range if view_range else None)
            if isinstance(result, str) and (result.startswith("Path not found") or result.startswith("Invalid command") or result.startswith("view_range") or result.startswith("start_line") or result.startswith("end_line") or result.startswith("Permission denied") or result.startswith("Unable to decode") or result.startswith("Error") or result.startswith("Path '")):
                return {"success": False, "error": result}
            return {"success": True, "message": result}
            
        elif command == "create":
            file_text = kwargs.get("file_text", "")
            result = text_file_create(command, path, file_text)
            if isinstance(result, str) and ("already exists" in result or "Permission denied" in result or "Error" in result):
                return {"success": False, "error": result}
            return {"success": True, "message": result}
            
        elif command == "str_replace":
            old_str = kwargs.get("old_str")
            new_str = kwargs.get("new_str")
            
            if old_str is None:
                return {"success": False, "error": "old_str parameter is required for str_replace command"}
            if new_str is None:
                return {"success": False, "error": "new_str parameter is required for str_replace command"}
            
            result = text_file_str_replace_in_file(command, path, old_str, new_str)
            if isinstance(result, str) and ("not found" in result or "Permission denied" in result or "Error" in result):
                return {"success": False, "error": result}
            return {"success": True, "message": result}
            
        elif command == "insert":
            insert_line = kwargs.get("insert_line")
            new_str = kwargs.get("new_str")
            
            if insert_line is None:
                return {"success": False, "error": "insert_line parameter is required for insert command"}
            if new_str is None:
                return {"success": False, "error": "new_str parameter is required for insert command"}
            
            result = text_file_insert_text_at_line(command, path, insert_line, new_str)
            if isinstance(result, str) and ("not found" in result or "Permission denied" in result or "Error" in result or "exceeds file length" in result):
                return {"success": False, "error": result}
            return {"success": True, "message": result}
            
        else:
            return {"success": False, "error": f"Unknown command: {command}"}
            
    except Exception as e:
        error_msg = f"Error executing command '{command}': {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"success": False, "error": error_msg}
