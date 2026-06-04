# Output Convention Update:
# -------------------------------------------------------------------------------
# All functions in this module must return either:
#   - A string result, or
#   - A dictionary with an explicit error field (or status), never None/null.
# Functions must never return None. Always provide a meaningful error string or
# error dictionary if an operation fails (e.g., "Error: <reason>").
# 
# NEW CONTRACT FOR ERRORS (filesystem/IO/subprocess/etc.):
#   - All public functions must return errors as a dict with an 'error' key and
#     a human-readable message, never as a string. No function may return None
#     or a string on error, except for ordinary operation messages.
#   - caller should always check for a dict with 'error' before using output.
#   - This contract applies to: cat_file, list_directory_contents, run_diff,
#     run_file_type, create_file, apply_patch, and any other public-facing
#     API. Even permission denied, file-not-found, malformed input, etc.
#   - Success output must NOT appear inside the 'error' dict – strictly use
#     'error' only for true errors.
# -------------------------------------------------------------------------------

import logging
import subprocess
import json
import os
import tempfile
from datetime import datetime
import shutil
import difflib
import mimetypes
from pathlib import Path

# Optional python-magic integration:
# Try to import the 'magic' module which is provided by the python-magic or
# python-magic-bin packages. python-magic binds to libmagic and typically
# provides more accurate MIME-type detection than the stdlib mimetypes module.
# If the import fails, HAVE_MAGIC will be False and the code will fall back to
# the existing mimetypes behavior.
try:
    import magic  # type: ignore
    HAVE_MAGIC = True
    MAGIC_MODULE = magic
except Exception:
    # Some environments may not have python-magic installed. In that case,
    # we gracefully disable this enhanced detection and continue to use
    # mimetypes as a portable fallback.
    HAVE_MAGIC = False
    MAGIC_MODULE = None

from monitor.lib.colors import print_yellow, print_blue, print_red, yellow, blue, red, reset

from pygments import highlight
from pygments.lexers import BashLexer, MarkdownLexer, DiffLexer
from pygments.formatters import TerminalFormatter

from monitor.lib.file_io import file_exists, read_file, write_file, create_file as fileio_create_file, delete_file, list_directory

logger = logging.getLogger(__name__)

def list_directory_contents(path: str = None):
    """
    List the contents of a directory.

    :param path: The path to the directory to list. If None, uses current working directory.
    :return: str: JSON-encoded result dict. On error or success, always returns a JSON string.
    """
    if path is not None:
        path = os.path.expanduser(path)
    logger.debug("Entering list_directory_contents function with path=%s", path)
    try:
        directory = path if path and path.strip() else os.getcwd()
        contents = list_directory(directory)
        if contents is None:
            logger.debug("Could not list contents of directory %s", directory)
            return json.dumps({"error": f"Could not list contents of directory '{directory}'."})
        print(f"{yellow}Listing {directory}{reset}")
        logger.debug("Listed contents of directory %s", directory)
        return json.dumps({"contents": contents})
    except Exception as e:
        print(f"{red}{str(e)}{reset}")
        logger.error("An unexpected error occurred: %s", str(e))
        return json.dumps({"error": f"An unexpected error occurred: {str(e)}"})

def cat_file(path: str):
    """
    Read and return the content of a file.

    :param path: The path to the file.
    :return: str: JSON-encoded result dict.
    """
    path = os.path.expanduser(path)
    logger.debug("Entering cat_file function with path=%s", path)
    try:
        logger.debug("Reading file %s", path)
        print(f"{yellow}Reading {path}{reset}")

        if not os.path.lexists(path):
            logger.debug("File %s does not exist", path)
            return json.dumps({"error": f"File '{path}' does not exist."})

        if os.path.islink(path):
            try:
                link_target = os.readlink(path)
                # For relative links, resolve relative to the symlink's directory
                if not os.path.isabs(link_target):
                    link_dir = os.path.dirname(os.path.abspath(path))
                    link_target_abs = os.path.normpath(os.path.join(link_dir, link_target))
                else:
                    link_target_abs = link_target
            except OSError as e:
                logger.error("Could not read symlink at %s: %s", path, str(e))
                return json.dumps({"error": f"Could not read symlink at '{path}': {str(e)}"})

            if not os.path.exists(link_target_abs):
                logger.error("Broken symlink: %s points to %s, which does not exist", path, link_target)
                return json.dumps({
                    "error": f"Broken symlink: '{path}' points to '{link_target}', which does not exist (absolute: '{link_target_abs}').",
                    "symlink": True,
                    "target": link_target,
                    "target_absolute": link_target_abs,
                    "broken": True
                })
            else:
                try:
                    content = read_file(path)
                except Exception as e:
                    logger.error("Permission or IO error when reading symlinked file %s (target %s): %s", path, link_target_abs, str(e))
                    return json.dumps({
                        "error": f"Permission or IO error when reading symlinked file '{path}' (target '{link_target_abs}'): {str(e)}",
                        "symlink": True,
                        "target": link_target,
                        "target_absolute": link_target_abs
                    })
                if content is None:
                    logger.error("Symlink %s points to %s, but target could not be read.", path, link_target)
                    return json.dumps({
                        "error": f"Symlink '{path}' points to '{link_target}', but the target could not be read.",
                        "symlink": True,
                        "target": link_target,
                        "target_absolute": link_target_abs
                    })
                # Normal case: symlink resolved successfully
                return json.dumps({
                    "content": content,
                    "symlink": True,
                    "target": link_target,
                    "target_absolute": link_target_abs,
                    "broken": False,
                    "message": f"'{path}' is a symlink to '{link_target_abs}'."
                })
        else:
            try:
                content = read_file(path)
            except Exception as e:
                logger.error("Error reading file %s: %s", path, str(e))
                return json.dumps({"error": f"Error reading file '{path}': {str(e)}"})
            if content is None:
                logger.error("File %s could not be read", path)
                return json.dumps({"error": f"File '{path}' could not be read."})
            return json.dumps({"content": content})
    except Exception as e:
        print(f"{red}{str(e)}{reset}")
        logger.error("Error reading file %s: %s", path, str(e))
        return json.dumps({"error": f"Error reading file {path}: {str(e)}"})

def cat_file_range(path: str, start_line: int, end_line: int):
    """
    Read and return a specific range of lines from a file.

    This function streams the file content and returns only the requested
    range of lines. Lines are 1-indexed. The function will not read the
    entire file into memory; it iterates the file line-by-line.

    Args:
        path (str): Path to the file to read (may be a symlink).
        start_line (int): 1-based line number to start reading from. Must be >= 1.
        end_line (int): 1-based line number to end reading at. Must be >= start_line.

    Returns:
        str: JSON-encoded dict. On success returns a dict with keys:
            - 'content': joined string of the returned lines (preserving line endings)
            - 'start_line': the provided start_line
            - 'end_line': the provided end_line
            - 'lines_returned': the actual number of lines returned
          On error returns a dict with an 'error' key describing the failure.
    """
    path = os.path.expanduser(path)
    logger.debug("Entering cat_file_range function with path=%s, start_line=%s, end_line=%s", path, start_line, end_line)
    try:
        # Validate range parameters
        try:
            if not isinstance(start_line, int) or not isinstance(end_line, int):
                logger.error("start_line and end_line must be integers. Received start_line=%s, end_line=%s", start_line, end_line)
                return json.dumps({"error": "Invalid range: start_line and end_line must be integers >= 1."})
            if start_line < 1 or end_line < 1:
                logger.error("Invalid range parameters: start_line=%s, end_line=%s", start_line, end_line)
                return json.dumps({"error": "Invalid range: start_line and end_line must be integers >= 1."})
            if end_line < start_line:
                logger.error("Invalid range: end_line (%s) is less than start_line (%s)", end_line, start_line)
                return json.dumps({"error": "Invalid range: end_line must be greater than or equal to start_line."})
        except Exception as e:
            logger.error("Error validating range parameters: %s", str(e))
            return json.dumps({"error": f"Invalid range parameters: {str(e)}"})

        # Compute number of lines requested based on start/end
        num_lines = end_line - start_line + 1

        logger.debug("Reading file range from %s: start_line=%d, end_line=%d (num_lines=%d)", path, start_line, end_line, num_lines)
        print(f"{yellow}Reading range from {path} (lines {start_line}..{end_line}){reset}")

        if not os.path.lexists(path):
            logger.debug("File %s does not exist", path)
            return json.dumps({"error": f"File '{path}' does not exist."})

        symlink_meta = None
        target_to_open = path

        if os.path.islink(path):
            try:
                link_target = os.readlink(path)
                # For relative links, resolve relative to the symlink's directory
                if not os.path.isabs(link_target):
                    link_dir = os.path.dirname(os.path.abspath(path))
                    link_target_abs = os.path.normpath(os.path.join(link_dir, link_target))
                else:
                    link_target_abs = link_target
            except OSError as e:
                logger.error("Could not read symlink at %s: %s", path, str(e))
                return json.dumps({"error": f"Could not read symlink at '{path}': {str(e)}"})

            if not os.path.exists(link_target_abs):
                logger.error("Broken symlink: %s points to %s, which does not exist", path, link_target)
                return json.dumps({
                    "error": f"Broken symlink: '{path}' points to '{link_target}', which does not exist (absolute: '{link_target_abs}').",
                    "symlink": True,
                    "target": link_target,
                    "target_absolute": link_target_abs,
                    "broken": True
                })
            else:
                symlink_meta = {
                    "symlink": True,
                    "target": link_target,
                    "target_absolute": link_target_abs,
                    "broken": False
                }
                # We can open the path directly; opening the symlink will follow to the target.
                target_to_open = path

        # Stream the file and collect requested lines
        lines = []
        lines_returned = 0
        try:
            with open(target_to_open, 'r', encoding='utf-8', errors='strict') as fh:
                for lineno, line in enumerate(fh, start=1):
                    if lineno < start_line:
                        continue
                    if lines_returned < num_lines:
                        lines.append(line)
                        lines_returned += 1
                    else:
                        break
        except UnicodeDecodeError as e:
            logger.error("Non-UTF8 content in file %s: %s", target_to_open, str(e))
            return json.dumps({"error": f"Non-UTF8 content encountered while reading file '{target_to_open}': {str(e)}"})
        except Exception as e:
            logger.error("Error reading file range %s: %s", target_to_open, str(e), exc_info=True)
            return json.dumps({"error": f"Error reading file '{target_to_open}': {str(e)}"})

        content = ''.join(lines)
        result = {
            "content": content,
            "start_line": start_line,
            "end_line": end_line,
            "lines_returned": lines_returned
        }
        if symlink_meta:
            result.update(symlink_meta)
            result["message"] = f"'{path}' is a symlink to '{symlink_meta['target_absolute']}'."

        logger.debug("Returning %d lines from %s (requested lines %d..%d)", lines_returned, target_to_open, start_line, end_line)
        return json.dumps(result)
    except Exception as e:
        print(f"{red}{str(e)}{reset}")
        logger.error("Exception in cat_file_range for %s: %s", path, str(e), exc_info=True)
        return json.dumps({"error": f"Exception reading file range: {str(e)}"})

def run_diff(file1: str, file2: str):
    """
    Run the diff command to compare two files.

    Args:
        file1 (str): Path to the original file.
        file2 (str): Path to the file with new contents.

    Returns:
        str: JSON-encoded result dict.
            On success: JSON dict with 'success', 'stdout', 'stderr', and 'returncode'.
            On error: JSON dict with 'error' and information.
    """
    file1 = os.path.expanduser(file1)
    file2 = os.path.expanduser(file2)
    logger.debug("Running diff between %s and %s", file1, file2)
    try:
        # If external 'diff' command is available, prefer it for fidelity to system diff.
        if shutil.which('diff'):
            diff = subprocess.run(['diff', '-u', file1, file2],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  text=True)
            logger.debug("Diff completed with returncode %d", diff.returncode)
            if diff.returncode == 0:
                result = {
                    "success": True,
                    "stdout": diff.stdout,
                    "stderr": diff.stderr,
                    "returncode": diff.returncode
                }
                return json.dumps(result)
            elif diff.returncode == 1:
                # 1 means differences found, so not an error
                result = {
                    "success": False,
                    "stdout": diff.stdout,
                    "stderr": diff.stderr,
                    "returncode": diff.returncode
                }
                return json.dumps(result)
            else:
                logger.error("Diff command failed with returncode %d: %s", diff.returncode, diff.stderr.strip())
                return json.dumps({
                    "error": f"Diff command failed with return code {diff.returncode}: {diff.stderr.strip()}",
                    "stderr": diff.stderr,
                    "returncode": diff.returncode
                })
        else:
            # Fallback: use Python's difflib to produce a unified diff if 'diff' is not available.
            # This ensures portability on Windows/macOS/Linux without requiring external tools.
            # Read and validate files first.
            if not os.path.exists(file1):
                logger.error("File not found: %s", file1)
                return json.dumps({"error": f"File '{file1}' does not exist."})
            if not os.path.exists(file2):
                logger.error("File not found: %s", file2)
                return json.dumps({"error": f"File '{file2}' does not exist."})
            try:
                content1 = read_file(file1)
            except Exception as e:
                logger.error("Error reading file %s for diff fallback: %s", file1, str(e))
                return json.dumps({"error": f"Error reading file '{file1}': {str(e)}"})
            try:
                content2 = read_file(file2)
            except Exception as e:
                logger.error("Error reading file %s for diff fallback: %s", file2, str(e))
                return json.dumps({"error": f"Error reading file '{file2}': {str(e)}"})
            if content1 is None:
                logger.error("File %s could not be read", file1)
                return json.dumps({"error": f"File '{file1}' could not be read."})
            if content2 is None:
                logger.error("File %s could not be read", file2)
                return json.dumps({"error": f"File '{file2}' could not be read."})
            # Use splitlines(True) to keep line endings similar to external diff.
            lines1 = content1.splitlines(True)
            lines2 = content2.splitlines(True)
            # Generate unified diff using difflib.
            # lineterm='' prevents difflib from adding additional line terminators.
            diff_lines = list(difflib.unified_diff(lines1, lines2, fromfile=file1, tofile=file2, lineterm=''))
            diff_text = ''.join(diff_lines)
            logger.debug("Python difflib produced %d diff lines", len(diff_lines))
            if not diff_lines:
                # No differences: mimic diff returncode 0
                return json.dumps({
                    "success": True,
                    "stdout": "",
                    "stderr": "",
                    "returncode": 0
                })
            else:
                # Differences found: mimic diff returncode 1
                return json.dumps({
                    "success": False,
                    "stdout": diff_text,
                    "stderr": "",
                    "returncode": 1
                })
    except Exception as e:
        print(f"{red}{str(e)}{reset}")
        logger.error("Exception running diff: %s", str(e))
        return json.dumps({"error": f"Exception running diff: {str(e)}"})

def run_file_type(path: str):
    """
    Run the 'file' command to get the mime type of a file.

    Args:
        path (str): Path to the file.

    Returns:
        str: JSON-encoded result dict.
            On success: JSON dict with 'success', 'stdout', 'stderr', and 'returncode'.
            On error: JSON dict with 'error' and information.
    """
    path = os.path.expanduser(path)
    logger.debug("Running file type check for %s", path)
    try:
        # If external 'file' command is available, use it for more accurate results.
        if shutil.which('file'):
            result = subprocess.run(['file', '--brief', '--mime-type', path],
                                    text=True, capture_output=True)
            logger.debug("Checked file type. Return code: %d", result.returncode)
            stdout = result.stdout.strip() if result.stdout else ""
            stderr = result.stderr.strip() if result.stderr else ""
            error_terms = ["cannot open", "no such file", "not found"]
            found_in_stdout = any(term in stdout.lower() for term in error_terms)
            found_in_stderr = any(term in stderr.lower() for term in error_terms)
            if result.returncode != 0 or found_in_stdout or found_in_stderr:
                err_message = stderr or stdout or "Unknown error"
                logger.error("File type command failed for %s: %s", path, err_message)
                return json.dumps({
                    "error": f"File type command failed with return code {result.returncode}: {err_message}",
                    "stderr": result.stderr,
                    "stdout": result.stdout,
                    "returncode": result.returncode
                })
            else:
                return json.dumps({
                    "success": True,
                    "stdout": stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode
                })
        else:
            # Fallback: try to use python-magic (libmagic bindings) if available.
            # python-magic (or python-magic-bin) typically provides a better
            # heuristic and binary inspection-based detection than mimetypes.
            # If HAVE_MAGIC is True, we use magic.Magic(mime=True).from_file(path).
            if not os.path.exists(path):
                logger.error("File not found for file type check: %s", path)
                return json.dumps({"error": f"File '{path}' does not exist."})
            if HAVE_MAGIC and MAGIC_MODULE is not None:
                try:
                    # Use python-magic to determine the MIME type from file contents.
                    mime_type = MAGIC_MODULE.Magic(mime=True).from_file(path)
                    # If magic returns bytes for some builds, decode if necessary
                    if isinstance(mime_type, bytes):
                        try:
                            mime_type = mime_type.decode('utf-8', errors='ignore')
                        except Exception:
                            mime_type = str(mime_type)
                    if not mime_type:
                        # Ensure we have a sensible default
                        mime_type = "application/octet-stream"
                    logger.debug("python-magic guessed mime type for %s: %s", path, mime_type)
                    return json.dumps({
                        "success": True,
                        "stdout": mime_type,
                        "stderr": "",
                        "returncode": 0
                    })
                except Exception as e:
                    # If python-magic fails for some reason, log and fall back to mimetypes below.
                    logger.error("Error using python-magic for %s: %s", path, str(e))
                    # Continue to the mimetypes fallback to provide a result.
            # Fallback: use Python's mimetypes and pathlib to guess the mime type.
            # This is less accurate than 'file' or python-magic, but portable across platforms.
            try:
                mime_type, encoding = mimetypes.guess_type(path)
                if not mime_type:
                    # Attempt to infer from extension or default to binary stream
                    ext = Path(path).suffix.lower()
                    if ext:
                        # Let mimetypes try registry again; otherwise default
                        mime_type = mimetypes.types_map.get(ext, None)
                    if not mime_type:
                        mime_type = "application/octet-stream"
                logger.debug("Guessed mime type for %s: %s (encoding: %s)", path, mime_type, encoding)
                return json.dumps({
                    "success": True,
                    "stdout": mime_type,
                    "stderr": "",
                    "returncode": 0
                })
            except Exception as e:
                logger.error("Error determining file type via mimetypes for %s: %s", path, str(e))
                return json.dumps({"error": f"Error determining file type: {str(e)}"})
    except subprocess.CalledProcessError as e:
        logger.error("Error determining file type: %s", str(e))
        return json.dumps({"error": f"Error determining file type: {str(e)}"})
    except Exception as e:
        print(f"{red}{str(e)}{reset}")
        logger.error("Exception running file command: %s", str(e), exc_info=True)
        return json.dumps({"error": f"Exception running file command: {str(e)}"})

def run_patch(patch_file_path: str):
    """
    Apply a patch file using the patch command.

    Args:
        patch_file_path (str): Path to the patch file.

    Returns:
        str: JSON-encoded result dict.
            On success: JSON dict with 'success', 'stdout', 'stderr', and 'returncode'.
            On error: JSON dict with 'error' and information.
    """
    patch_file_path = os.path.expanduser(patch_file_path)
    logger.debug("Running patch with patch file %s", patch_file_path)
    try:
        # If external 'patch' command is available, use it.
        if shutil.which('patch'):
            # Pass the patch via stdin with list args (no shell) so a path like
            # "x; rm -rf ~" can't be interpreted by a shell. timeout guards
            # against a patch that prompts and hangs waiting on input.
            with open(patch_file_path, 'r', encoding='utf-8') as patch_fh:
                result = subprocess.run(
                    ['patch', '-p0'],
                    stdin=patch_fh,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            if result.returncode == 0:
                logger.debug("Patch command succeeded")
                return json.dumps({
                    "success": True,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode
                })
            else:
                logger.error("Patch command failed with returncode %d: %s", result.returncode, result.stderr.strip())
                return json.dumps({
                    "error": f"Patch command failed with return code {result.returncode}: {result.stderr.strip()}",
                    "stderr": result.stderr,
                    "stdout": result.stdout,
                    "returncode": result.returncode
                })
        else:
            # Fallback: inform the user that 'patch' is not available and provide actionable guidance.
            msg = (
                "Patch utility 'patch' is not available on this system. "
                "Install 'patch' (e.g., on Windows use GnuWin32, Cygwin, or Windows Subsystem for Linux, "
                "or use 'git apply' as an alternative)."
            )
            logger.error(msg + " Patch file: %s", patch_file_path)
            return json.dumps({
                "error": msg,
                "patch_file": patch_file_path
            })
    except FileNotFoundError:
        logger.error("Patch file does not exist: %s", patch_file_path)
        return json.dumps({"error": f"Patch file '{patch_file_path}' does not exist."})
    except subprocess.TimeoutExpired:
        logger.error("Patch command timed out for %s", patch_file_path)
        return json.dumps({"error": "Patch command timed out after 60s."})
    except subprocess.CalledProcessError as e:
        logger.error("Patch failed: %s", e.stderr)
        return json.dumps({
            "error": f"Patch command failed: {e.stderr}",
            "stderr": e.stderr,
            "stdout": "",
            "returncode": e.returncode if hasattr(e, "returncode") else -1
        })
    except Exception as e:
        print(f"{red}{str(e)}{reset}")
        logger.error("Exception running patch: %s", str(e), exc_info=True)
        return json.dumps({"error": f"Exception running patch command: {str(e)}"})

def create_patch_for_file(path: str, contents: str):
    """
    Create a patch file for updating the contents of a file at the given path.

    :param path: The path to the file to update.
    :param contents: The string contents to write to the file.
    :return: str: JSON-encoded result dict. On error or success, always returns a JSON string.
    """
    path = os.path.expanduser(path)
    logger.debug("Entering create_patch_for_file function with path=%s", path)
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            new_content_path = os.path.join(temp_dir, 'new_content')
            write_file(new_content_path, contents)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            patch_filename = f"{os.path.basename(path)}_{timestamp}.patch"
            patch_path = os.path.join(os.path.dirname(path), patch_filename)
            try:
                diff_result_json = run_diff(path, new_content_path)
                diff_result = json.loads(diff_result_json)
                if isinstance(diff_result, dict) and "error" in diff_result:
                    logger.error("Error creating patch (diff failed): %s", diff_result["error"])
                    return json.dumps({"error": f"Error creating patch: {diff_result['error']}"})
                if diff_result.get("success"):
                    write_file(patch_path, diff_result["stdout"])
                    logger.info("Created patch file at %s", patch_path)
                    return json.dumps({"patch_path": patch_path})
                else:
                    logger.error("Error creating patch: %s", diff_result.get("stderr", ""))
                    return json.dumps({"error": f"Error creating patch: {diff_result.get('stderr', '')}"})
            except Exception as e:
                logger.error("Error creating patch: %s", str(e), exc_info=True)
                return json.dumps({"error": f"Error creating patch: {str(e)}"})
    except Exception as e:
        print(f"{red}{str(e)}{reset}")
        logger.error("Error in patch creation process: %s", str(e), exc_info=True)
        return json.dumps({"error": f"Error in patch creation process: {str(e)}"})

def create_file(path, contents, overwrite=False):
    """
    Create a file with the given content, creating parent directories as needed.

    Default behavior is safe (refuse to overwrite). Set ``overwrite=True``
    when the caller has already inspected the existing file and explicitly
    intends to replace its contents — see the tool schema for guidance on
    when each form is appropriate. The directory-collision check is
    unaffected by ``overwrite``: a path that exists as a directory is
    always rejected.

    Args:
        path (str): The file path to create. ``~`` is expanded.
        contents (str): The content to write.
        overwrite (bool): When False (default), refuses with an error if a
            file already exists at ``path``. When True, replaces the existing
            file's contents.

    Returns:
        str: JSON-encoded result dict with ``result`` on success or ``error``
        on failure. On success, includes ``overwritten: True/False`` so callers
        can confirm whether a pre-existing file was replaced.
    """
    path = os.path.expanduser(path)
    logger.debug(
        "Entering create_file function with path=%s, overwrite=%s",
        path, overwrite,
    )

    # Blast-radius cap: reject oversized writes before doing any disk work.
    # Checked at call time (not import time) so MAX_FILE_WRITE_BYTES can be
    # monkeypatched in tests and reloaded at runtime via YAML.
    from monitor.lib.safety import check_write_size
    ok, err = check_write_size(contents, "create_file")
    if not ok:
        logger.warning("create_file: %s", err)
        return json.dumps({"error": err})

    # Ensure parent directory exists before attempting creation
    parent_dir = os.path.dirname(path)
    if parent_dir and not os.path.exists(parent_dir):
        try:
            os.makedirs(parent_dir, exist_ok=True)
            logger.debug("Created parent directories for %s", path)
        except Exception as e:
            logger.error("Error creating parent directories for %s: %s", path, str(e), exc_info=True)
            print_red(f"Error creating parent directories for {path}: {str(e)}")
            return json.dumps({"error": f"Error creating parent directories for {path}: {str(e)}"})

    # Validate path state. The directory check is non-negotiable — writing a
    # file at a directory path is never sensible.
    if os.path.isdir(path):
        logger.error("Path exists and is a directory: %s", path)
        print_red(f"Path exists and is a directory: {path}")
        return json.dumps({"error": f"Path exists and is a directory: {path}"})

    pre_existing = file_exists(path)
    if pre_existing and not overwrite:
        # Demoted from WARNING to INFO: this is an expected branch the caller
        # can recover from (set overwrite=True after inspecting the file, or
        # use a targeted-edit tool). It's not an error condition.
        logger.info("File already exists at %s; refusing to overwrite (overwrite=False)", path)
        return json.dumps({
            "error": (
                f"File already exists at {path}; not overwritten. "
                "Pass overwrite=True to replace it, or use "
                "text_file_str_replace_in_file for a targeted edit instead."
            )
        })

    # Attempt file creation/overwrite using the underlying IO helper. The
    # helper handles overwrite at the syscall level (open with "w" mode).
    try:
        creation_ok = fileio_create_file(path, contents, overwrite=overwrite)
    except TypeError:
        # Backward-compat: fileio_create_file may not accept the kwarg in
        # older builds. Fall back to the param-less call, which only works
        # for the create-new branch.
        try:
            creation_ok = fileio_create_file(path, contents)
        except Exception as e:
            logger.error("Exception during file creation at %s: %s", path, str(e), exc_info=True)
            print_red(f"Error creating file at {path}: {str(e)}")
            return json.dumps({"error": f"Error creating file at {path}: {str(e)}"})
    except Exception as e:
        logger.error("Exception during file creation at %s: %s", path, str(e), exc_info=True)
        print_red(f"Error creating file at {path}: {str(e)}")
        return json.dumps({"error": f"Error creating file at {path}: {str(e)}"})

    if not creation_ok:
        logger.error("Underlying file creation function reported failure for %s", path)
        print_red(f"Failed to create file at {path}.")
        return json.dumps({"error": f"Failed to create file at {path}."})

    action = "Replaced" if pre_existing else "Created"
    logger.info("%s file at %s", action, path)
    print_yellow(f"{action} file at {path}.")
    return json.dumps({
        "result": f"{action} file at {path}.",
        "overwritten": pre_existing,
    })

def make_directory(path: str):
    """
    Create a directory (and parents as needed) at the given path.

    - Expands '~' in the path.
    - Validates that the path is a non-empty string.
    - If the path exists and is a directory: returns JSON with result message and created=false.
    - If the path exists and is not a directory: returns JSON with an 'error' message.
    - Otherwise, creates the directory and returns JSON with result message and created=true.

    Returns:
        str: JSON-encoded result dict.
    """
    logger.debug("Entering make_directory function with path=%s", path)
    if not isinstance(path, str) or not path.strip():
        logger.error("Invalid path: must be a non-empty string.")
        return json.dumps({"error": "Invalid path: must be a non-empty string."})
    try:
        path = os.path.expanduser(path)
        logger.debug("Expanded path to %s", path)
        if os.path.exists(path):
            if os.path.isdir(path):
                logger.info("Directory already exists at %s", path)
                print_yellow(f"Directory already exists: {path}")
                return json.dumps({"result": "Directory already exists", "path": path, "created": False})
            else:
                logger.error("Path exists and is not a directory: %s", path)
                print_red(f"Path exists and is not a directory: {path}")
                return json.dumps({"error": f"Path exists and is not a directory: {path}"})
        else:
            os.makedirs(path, exist_ok=True)
            logger.info("Directory created at %s", path)
            print_yellow(f"Directory created at {path}.")
            return json.dumps({"result": "Directory created", "path": path, "created": True})
    except Exception as e:
        print_red(f"Error creating directory: {str(e)}")
        logger.error("Error creating directory %s: %s", path, str(e), exc_info=True)
        return json.dumps({"error": f"Error creating directory: {str(e)}"})

def apply_patch(patch_file_path):
    """
    Apply a patch file using the patch command.

    :param patch_file_path: Fully qualified path to the patch file.
    :return: str: JSON-encoded result dict. On error or success, always returns a JSON string.
    """
    patch_file_path = os.path.expanduser(patch_file_path)
    logger.debug("Entering apply_patch function with patch_file_path=%s", patch_file_path)
    patch_result_json = run_patch(patch_file_path)
    patch_result = json.loads(patch_result_json)
    if isinstance(patch_result, dict) and "error" in patch_result:
        print_red(f"An error occurred while applying the patch: {patch_result['error']}")
        logger.error("An error occurred while applying the patch %s: %s", patch_file_path, patch_result["error"])
        return json.dumps({"error": f"An error occurred while applying the patch: {patch_result['error']}"})
    if patch_result.get("success"):
        print_yellow("Patch applied successfully:")
        print_blue(patch_result["stdout"])
        logger.info("Patch %s applied successfully", patch_file_path)
        return json.dumps({"result": f"Applied patch {patch_result['stdout']}"})
    else:
        print_red(f"An error occurred while applying the patch: {patch_result.get('stderr', '')}")
        logger.error("An error occurred while applying the patch %s: %s", patch_file_path, patch_result.get("stderr", ""))
        return json.dumps({"error": f"An error occurred while applying the patch: {patch_result.get('stderr', '')}"})

def file_type(path: str):
    """
    Provides the file type of a given file at the specified path.

    Parameters:
    path (str): The path to the file to check

    Returns:
    str: JSON-encoded result dict.
    """
    path = os.path.expanduser(path)
    logger.debug("Entering file_type function with path=%s", path)
    result_json = run_file_type(path)
    result = json.loads(result_json)
    if isinstance(result, dict) and "error" in result:
        logger.error("Error determining file type for %s: %s", path, result["error"])
        return json.dumps({"error": f"Error determining file type: {result['error']}"})
    if result.get("success"):
        logger.debug("Checked file type of %s", path)
        return json.dumps({"type": result["stdout"]})
    else:
        logger.error("Error determining file type for %s: %s", path, result.get("stderr", ""))
        return json.dumps({"error": f"Error determining file type: {result.get('stderr', '')}"})

def print_diff(diff_output: str):
    """
    Pretty-print a diff using syntax highlighting in the terminal.

    Args:
        diff_output (str): The unified diff output to display.
    """
    if diff_output:
        highlighted_output = highlight(diff_output, DiffLexer(), TerminalFormatter(reset=True))
        print(highlighted_output)
    else:
        print_yellow("No differences found.")


# End of module: No additional code follows.
