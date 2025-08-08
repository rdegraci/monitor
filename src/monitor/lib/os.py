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
            logger.error("Could not list contents of directory %s", directory)
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
            logger.error("File %s does not exist", path)
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
        command = f'patch -p0 < {patch_file_path}'
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
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

def create_file(path, contents):
    """
    Creates a new file with the given content if the file does NOT already exist.

    If the file exists:
      - Do NOT overwrite it; instead, log and print a warning or error.
      - Return JSON string with {'error': <msg>}.

    If the file does not exist:
      - Create the file with the given content.
      - Log and print success.
      - Return JSON string with a result message.

    :param path: The file path to create.
    :param contents: The contents to write in the new file.

    :return: str: JSON-encoded result dict.
    """
    path = os.path.expanduser(path)
    logger.debug("Entering create_file function with path=%s", path)
    if file_exists(path):
        logger.warning("File already exists at %s; will not overwrite", path)
        return json.dumps({"error": f"File already exists at {path}; not overwritten."})
    else:
        try:
            fileio_create_file(path, contents)
            logger.info("Created new file at %s", path)
            print_yellow(f"Created new file at {path}.")
            return json.dumps({"result": f"Created new file at {path}."})
        except Exception as e:
            logger.error("Error creating file: %s", str(e), exc_info=True)
            print_red(f"Error creating file: {str(e)}")
            return json.dumps({"error": f"Error creating file: {str(e)}"})

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
